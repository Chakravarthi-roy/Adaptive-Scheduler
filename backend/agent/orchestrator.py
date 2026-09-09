"""
orchestrator.py — the pipeline itself

REWORKED: there's no upfront keyword classifier gating which prompt gets
used anymore (that was router.py's job). Every turn now sees the SAME
unified AGENT_PROMPT with every action available, and decides fresh from
the full conversation what to do — see prompts.py for why.

Two knock-on effects of removing the classifier:

1. Guardrails that used to key off the GUESSED intent (e.g. "is intent ==
   create") now key off the ACTUAL action the model chose instead. See the
   demo-cap check inside run_loop, at the create_reminder branch — it now
   catches every path that leads to a create attempt, not just conversations
   that were classified as "create" from message #1.

2. The "intent" label returned to the frontend (used only so chat.js/modal.js
   can tell "the thing this conversation was about just finished" apart from
   "a side-action happened, keep going") is now derived AFTER the fact, from
   whichever terminal action the model actually took — see
   _infer_session_intent below. The first terminal action in a conversation
   anchors it; later side-actions of a different type don't override that
   anchor, same behavior chat.js already relies on, just built on real
   evidence instead of a keyword guess.

Each step below still has its OWN error handling, so a failure in one step
is identifiable and doesn't take down the whole request:
  1. the LLM call itself (network/API failure)
  2. parsing its output as JSON (malformed response)
  3. dispatching to a tool (DB/query failure — tools already catch their own
     exceptions and return {"error": ...}, this step reacts to that signal)
"""

from datetime import datetime
import groq, json, os

from .context import get_user_tz, get_demo_status
from .prompts import AGENT_PROMPT
from .tools import (
    get_reminders_tool,
    get_all_reminders_tool,
    update_reminder_tool,
    delete_reminders_tool,
    find_schedule_gaps_tool,
    search_reminders_tool,
)

client = groq.Groq(api_key=os.getenv("GROQ_API_KEY"), timeout=60.0)

# Shown when a demo user tries to create a reminder after already using
# their one allowed reminder (reminders.py POST /reminders enforces the
# actual hard cap — this is the agent knowing about it and stopping BEFORE
# a wasted multi-turn conversation, wherever a create is attempted from).
DEMO_CAP_REACHED_TEXT = (
    "Demo mode only allows one reminder — create a free account to add more! "
    "Want me to check or update your existing one instead?"
)

# Maps a terminal action (one that actually changes/answers something,
# as opposed to a mid-conversation ask_user or an intermediate tool fetch)
# to the coarse "intent" label the frontend uses for its own bookkeeping.
# "answer_user" covers real query answers AND the out-of-scope decline —
# frontend doesn't need to tell those apart, so both map to "query".
_TERMINAL_ACTION_INTENT = {
    "create_reminder":  "create",
    "update_reminder":  "update",
    "delete_reminder":  "delete",
    "search_reminders": "query",
    "find_gaps":         "query",
    "answer_user":       "query",
}


def _call_llm(full_messages: list):
    """Step 1: the model call. Isolated so a network/API failure here is
    distinguishable from a downstream parsing or tool failure."""
    try:
        response = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=full_messages,
            temperature=0
        )
        return response.choices[0].message.content.strip(), None
    except Exception as e:
        print(f"[orchestrator] LLM call failed: {type(e).__name__}: {e}")
        return None, "Having trouble reaching the assistant right now — try again in a moment!"


def _strip_fences(text: str) -> str:
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    return text


def _parse_action(text: str):
    """Step 2: parse the model's JSON. Isolated so a malformed response is
    distinguishable from a network failure or a tool failure."""
    text = _strip_fences(text)
    try:
        return json.loads(text), None
    except json.JSONDecodeError as e:
        print(f"[orchestrator] JSON parse failed: {e} — raw text: {text!r}")
        return None, "Sorry, I had trouble understanding that. Try again!"


def _infer_session_intent(messages: list, current_action: str | None) -> str | None:
    """
    Figures out this conversation's 'primary' intent for the frontend — NOT
    by guessing upfront from keywords (that was the bug), but by looking at
    what the model has ACTUALLY done. Scans prior assistant turns for the
    earliest terminal action already taken in this conversation and anchors
    to that, so a later side-action of a different type doesn't overwrite
    it. If nothing terminal has happened yet, falls back to whatever action
    is being taken THIS turn.
    """
    for m in messages:
        if m.get("role") != "assistant":
            continue
        parsed, err = _parse_action(m.get("content", ""))
        if err or not parsed:
            continue
        mapped = _TERMINAL_ACTION_INTENT.get(parsed.get("action"))
        if mapped:
            return mapped   # earliest match wins — messages are in order
    return _TERMINAL_ACTION_INTENT.get(current_action)


async def run_loop(messages: list, system: str, user_id: str, now_str: str) -> dict:
    """
    Single reasoning loop — every action is available every turn, the model
    decides what's needed from the full conversation each time.

    Every return carries full_messages[1:] (the whole conversation minus the
    system prompt) — not the bare input `messages`. Returning only the input
    would silently drop the assistant's own tool calls, fetched data, and
    prior questions from the history sent back next turn, leaving the model
    with no memory of what it already asked or fetched.

    Also returns "_action" (the raw action string chosen, when terminal) so
    run_agent can compute the session intent — popped before the response
    goes back to the frontend.
    """
    full_messages = [
        {"role": "system", "content": f"{system}\n\nCurrent date and time: {now_str}"}
    ] + messages

    for _ in range(8):   # max 8 iterations — enough for any workflow
        text, err = _call_llm(full_messages)
        if err:
            return {"type": "error", "text": err}

        data, err = _parse_action(text)
        if err:
            return {"type": "error", "text": err}

        action = data.get("action")
        full_messages.append({"role": "assistant", "content": text})

        # ── Step 3: tool dispatch — each tool already catches its own
        # exceptions and returns {"error": "..."} on failure; we surface that
        # to the model as an observation rather than crashing, so it can tell
        # the user something went wrong instead of hallucinating an answer. ──

        if action == "get_reminders":
            result = get_reminders_tool(user_id)
            full_messages.append({"role": "user", "content": f"Current active reminders: {json.dumps(result)}"})

        elif action == "get_all_reminders":
            result = get_all_reminders_tool(user_id)
            full_messages.append({"role": "user", "content": f"Full reminder history (including done and missed): {json.dumps(result)}"})

        elif action == "find_gaps":
            result = find_schedule_gaps_tool(
                user_id, data.get("date"), data.get("work_start", "07:00"), data.get("work_end", "18:00")
            )
            full_messages.append({"role": "user", "content": f"Computed schedule gaps: {json.dumps(result)}"})

        elif action == "search_reminders":
            result = search_reminders_tool(
                user_id, query_text=data.get("query_text"),
                relative_range=data.get("relative_range"), status=data.get("status")
            )
            full_messages.append({"role": "user", "content": f"Search results: {json.dumps(result)}"})

        elif action == "ask_user":
            return {
                "type": "question",
                "text": data.get("question", "Can you tell me a bit more?"),
                "messages": full_messages[1:]
            }

        elif action == "create_reminder":
            # Guardrail keyed off the ACTUAL action, not a guessed intent —
            # catches a demo cap hit from ANY conversation shape, not just
            # ones a keyword classifier happened to label "create" upfront.
            is_demo, reminder_count = get_demo_status(user_id)
            if is_demo and reminder_count >= 1:
                print(f"[orchestrator] demo cap reached — user={user_id[:8]}...")
                return {
                    "type": "answer",
                    "text": DEMO_CAP_REACHED_TEXT,
                    "items": [],
                    "messages": full_messages[1:],
                    "_action": "answer_user"
                }
            return {"type": "reminder", "data": data, "messages": full_messages[1:], "_action": action}

        elif action == "update_reminder":
            result = update_reminder_tool(data, user_id)
            if "error" in result:
                return {"type": "error", "text": result["error"]}
            return {"type": "updated", "text": data.get("confirmation", "Done!"), "messages": full_messages[1:], "_action": action}

        elif action == "delete_reminder":
            result = delete_reminders_tool(data.get("ids", []), user_id)
            if "error" in result:
                return {"type": "error", "text": result["error"]}
            return {"type": "deleted", "text": data.get("confirmation", "Deleted."), "messages": full_messages[1:], "_action": action}

        elif action == "answer_user":
            return {
                "type": "answer",
                "text": data.get("text", ""),
                "items": data.get("items", []),
                "messages": full_messages[1:],
                "_action": action
            }

        else:
            print(f"[orchestrator] Unknown action returned: {action}")
            return {"type": "error", "text": "Sorry, something went wrong. Try rephrasing!"}

    return {"type": "error", "text": "I got a bit confused — could you try rephrasing that?"}


async def run_agent(messages: list, user_id: str) -> dict:
    """Entry point: context → single unified reasoning loop.

    No upfront intent classifier — see prompts.py's module docstring for
    why. "Intent" for the frontend is derived after the loop runs, from
    what actually happened, not guessed before it starts.
    """
    tz      = get_user_tz(user_id)
    now     = datetime.now(tz)
    now_str = now.strftime("%A, %d %B %Y %I:%M %p (%Z)")

    result = await run_loop(messages, AGENT_PROMPT, user_id, now_str)

    current_action = result.pop("_action", None)
    result["intent"] = _infer_session_intent(messages, current_action)

    return result
"""
orchestrator.py — the pipeline itself

Ties together: router → prompt selection → reasoning/acting loop → tools →
memory (conversation history + DB). This is the only file that knows about
all the other pieces; router/tools/prompts/context don't know about each
other.

Each step below has its OWN error handling, so a failure in one step is
identifiable and doesn't take down the whole request:
  1. the LLM call itself (network/API failure)
  2. parsing its output as JSON (malformed response)
  3. dispatching to a tool (DB/query failure — tools already catch their own
     exceptions and return {"error": ...}, this step reacts to that signal)

None of this adds latency in the normal (non-failing) path — a try/except
that doesn't trigger costs nothing measurable in Python.
"""

from datetime import datetime
import groq, json, os

from .router import classify_intent
from .context import get_user_tz
from .prompts import PROMPT_MAP, CREATE_PROMPT
from .tools import (
    get_reminders_tool,
    get_all_reminders_tool,
    update_reminder_tool,
    delete_reminders_tool,
    find_schedule_gaps_tool,
    search_reminders_tool,
)

client = groq.Groq(api_key=os.getenv("GROQ_API_KEY"), timeout=60.0)


def _call_llm(full_messages: list):
    """Step 1: the model call. Isolated so a network/API failure here is
    distinguishable from a downstream parsing or tool failure."""
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=full_messages,
            temperature=0
        )
        return response.choices[0].message.content.strip(), None
    except Exception as e:
        print(f"[orchestrator] LLM call failed: {type(e).__name__}: {e}")
        return None, "Having trouble reaching the assistant right now — try again in a moment!"


def _parse_action(text: str):
    """Step 2: parse the model's JSON. Isolated so a malformed response is
    distinguishable from a network failure or a tool failure."""
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text), None
    except json.JSONDecodeError as e:
        print(f"[orchestrator] JSON parse failed: {e} — raw text: {text!r}")
        return None, "Sorry, I had trouble understanding that. Try again!"


async def run_loop(messages: list, system: str, user_id: str, now_str: str) -> dict:
    """
    Single reusable loop used by all four workflows.

    Every return carries full_messages[1:] (the whole conversation minus the
    system prompt) — not the bare input `messages`. Returning only the input
    would silently drop the assistant's own tool calls, fetched data, and
    prior questions from the history sent back next turn, leaving the model
    with no memory of what it already asked or fetched — which is what
    caused repeated questions and redundant re-fetches before this fix.
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
            return {"type": "reminder", "data": data, "messages": full_messages[1:]}

        elif action == "update_reminder":
            result = update_reminder_tool(data, user_id)
            if "error" in result:
                return {"type": "error", "text": result["error"]}
            return {"type": "updated", "text": data.get("confirmation", "Done!"), "messages": full_messages[1:]}

        elif action == "delete_reminder":
            result = delete_reminders_tool(data.get("ids", []), user_id)
            if "error" in result:
                return {"type": "error", "text": result["error"]}
            return {"type": "deleted", "text": data.get("confirmation", "Deleted."), "messages": full_messages[1:]}

        elif action == "answer_user":
            return {
                "type": "answer",
                "text": data.get("text", ""),
                "items": data.get("items", []),
                "messages": full_messages[1:]
            }

        else:
            print(f"[orchestrator] Unknown action returned: {action}")
            return {"type": "error", "text": "Sorry, something went wrong. Try rephrasing!"}

    return {"type": "error", "text": "I got a bit confused — could you try rephrasing that?"}


async def run_agent(messages: list, user_id: str) -> dict:
    """Entry point: router → context → loop."""
    tz      = get_user_tz(user_id)
    now     = datetime.now(tz)
    now_str = now.strftime("%A, %d %B %Y %I:%M %p (%Z)")

    # Classify intent from the first user message in this conversation.
    # Multi-turn follow-ups (answer to clarifying question) carry the same
    # intent implicitly, so classifying once from the first message is enough.
    first_user_msg = next((m["content"] for m in messages if m.get("role") == "user"), "")
    intent = classify_intent(first_user_msg)
    system = PROMPT_MAP.get(intent, CREATE_PROMPT)

    print(f"[agent] intent={intent} user={user_id[:8]}...")
    return await run_loop(messages, system, user_id, now_str)
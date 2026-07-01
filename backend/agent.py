"""
agent.py — Nudge AI agent

Architecture: intent router → specialized workflow
Each workflow has its own focused prompt and only the tools it needs.

Workflows:
  create  — extract and confirm a new reminder
  update  — find and modify an existing reminder
  delete  — find and remove one or more reminders
  query   — answer questions about the schedule (gaps, history, etc.)
"""

from datetime import datetime
from database import SessionLocal, Reminder, User
import groq, json, os, pytz

client = groq.Groq(api_key=os.getenv("GROQ_API_KEY"), timeout=60.0)


# ─── Intent Classification ─────────────────────────────────────────────────────
# Rule-based — no extra LLM call, instant, zero cost.
# Falls back to "create" which is by far the most common intent.

_QUERY_SIGNALS  = [
    "do i have", "what do i have", "show me", "list", "check",
    "any gaps", "free time", "did i", "have i", "when is", "when was",
    "what time", "how many", "any reminders"
]
_DELETE_SIGNALS = [
    "delete", "remove", "cancel", "forget", "drop", "clear",
    "stop reminding", "dismiss", "get rid of"
]
_UPDATE_SIGNALS = [
    "update", "change", "move", "reschedule", "edit", "modify",
    "shift", "postpone", "delay", "bring forward", "earlier", "later",
    "rename", "push to", "push it"
]


def _classify_intent(text: str) -> str:
    t = text.lower()
    if any(s in t for s in _QUERY_SIGNALS):  return "query"
    if any(s in t for s in _DELETE_SIGNALS): return "delete"
    if any(s in t for s in _UPDATE_SIGNALS): return "update"
    return "create"


# ─── User Timezone ─────────────────────────────────────────────────────────────

def _get_user_tz(user_id: str) -> pytz.BaseTzInfo:
    """Get user's saved timezone from DB, fall back to IST if not set."""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        tz_str = getattr(user, "timezone", None) or "Asia/Kolkata"
        try:
            return pytz.timezone(tz_str)
        except pytz.UnknownTimeZoneError:
            return pytz.timezone("Asia/Kolkata")
    finally:
        db.close()


# ─── Tool Handlers ─────────────────────────────────────────────────────────────

def get_reminders_tool(user_id: str) -> list:
    """Active reminders only — used by create / update / delete workflows."""
    db = SessionLocal()
    try:
        reminders = db.query(Reminder).filter(
            Reminder.user_id == user_id,
            Reminder.done == False
        ).order_by(Reminder.datetime).all()
        return [
            {
                "id":       r.id,
                "title":    r.title,
                "datetime": r.datetime.isoformat() if r.datetime else None,
                "type":     r.type,
                "repeat":   r.repeat,
                "location": r.location or ""
            }
            for r in reminders
        ]
    finally:
        db.close()


def get_all_reminders_tool(user_id: str) -> list:
    """All reminders including done and missed — used by query workflow only."""
    db = SessionLocal()
    try:
        reminders = db.query(Reminder).filter(
            Reminder.user_id == user_id
        ).order_by(Reminder.datetime).all()
        return [
            {
                "id":       r.id,
                "title":    r.title,
                "datetime": r.datetime.isoformat() if r.datetime else None,
                "type":     r.type,
                "repeat":   r.repeat,
                "location": r.location or "",
                "done":     r.done,
                "missed":   getattr(r, "missed", False)
            }
            for r in reminders
        ]
    finally:
        db.close()


def update_reminder_tool(action_data: dict, user_id: str) -> dict:
    reminder_id = action_data.get("id")
    db = SessionLocal()
    try:
        reminder = db.query(Reminder).filter(
            Reminder.id == str(reminder_id),
            Reminder.user_id == user_id
        ).first()
        if not reminder:
            return {"status": "not found"}
        if action_data.get("title"):
            reminder.title    = action_data["title"]
        if action_data.get("datetime"):
            reminder.datetime = datetime.fromisoformat(action_data["datetime"])
        if action_data.get("location"):
            reminder.location = action_data["location"]
        if action_data.get("pre_alert_minutes") is not None:
            reminder.pre_alert_minutes = str(action_data["pre_alert_minutes"])
        if action_data.get("follow_up_minutes") is not None:
            reminder.follow_up_minutes = str(action_data["follow_up_minutes"])
        # Reset notification flags so updated reminder fires again correctly
        reminder.notified       = False
        reminder.pre_alerted    = False
        reminder.follow_up_sent = False
        db.commit()
        return {"status": "updated"}
    finally:
        db.close()


def delete_reminders_tool(ids: list, user_id: str) -> dict:
    db = SessionLocal()
    try:
        deleted = 0
        for rid in ids:
            reminder = db.query(Reminder).filter(
                Reminder.id == rid,
                Reminder.user_id == user_id
            ).first()
            if reminder:
                db.delete(reminder)
                deleted += 1
        db.commit()
        return {"deleted": deleted}
    finally:
        db.close()


# ─── Workflow Prompts ──────────────────────────────────────────────────────────
# Each prompt only describes what that workflow needs — no noise from others.
# Shared formatting rules are appended to keep individual prompts short.

_SHARED = """
Respond ONLY with valid JSON — no extra text, no markdown, no code fences.
Strip filler words like ra, yaar, na, bro, da from any titles.
Be concise and conversational in any confirmation, question, or answer."""


CREATE_PROMPT = """You are Nudge — a smart reminder assistant. Your only job right now is to create a new reminder.

WORKFLOW:
1. Call get_reminders to see the existing schedule (resolves relative times like "after my exam")
2. Extract everything you can from what the user said and infer the rest
3. Only call ask_user if the time/date is completely missing AND cannot be inferred
4. Call create_reminder with all fields filled

TIME RULES:
- datetime format: YYYY-MM-DDTHH:MM:00 — use "" if no specific time at all
- "evening" = 18:00, "morning" = 08:00, "night" = 21:00
- "in a bit" = 10 min from now, "after a while" = 30 min from now
- "next sunday" = sunday of next week
- "8 o'clock" with no AM/PM: infer from context and current time

TYPE — pick the single best fit:
- important: high-stakes, real consequences if missed (exams, interviews, deadlines)
- health: medicine, workouts, doctor visits, anything body-related
- routine: repeating small habits (drink water, study, daily check-ins)
- personal: specific purposeful one-off tasks (buy X, call Y, pick up Z)
- casual: vague time-based nudge with nothing specific riding on it

ACTION LABEL — what the user physically DOES when the reminder fires:
- Specific, under 5 words, emoji if it fits naturally
- "Having lunch 🍜" not "Done ✓" for lunch
- "Took it 💊" for medication, "Called her ✓" for calls

PRE-ALERT — only set non-zero if there is genuinely something to prepare:
- 0 for: drink water, stretch, take a break, check messages, simple nudges — anything with no real prep step
- Non-zero for: meetings with travel, exams, medication needing setup, getting-ready steps
- Range: 2–60 when non-zero. Default to 0.

FOLLOW-UP — only if completion tracking matters:
- 0 for: casual reminders, simple one-second actions, vague nudges
- 10 for: medication
- 15–20 for: send/submit/reply tasks
- 60 for: meetings or exams without a stated duration
- Default to 0.

NEVER ask for location, participants, or other optional fields — leave them empty.

Valid responses:
{"action": "get_reminders"}
{"action": "ask_user", "question": "..."}
{"action": "create_reminder", "title": "...", "datetime": "...", "location": "", "type": "...", "repeat": "none", "participants": [], "action_label": "...", "pre_alert_minutes": 0, "follow_up_minutes": 0}
""" + _SHARED


UPDATE_PROMPT = """You are Nudge — a smart reminder assistant. Your only job right now is to update an existing reminder.

WORKFLOW:
1. Call get_reminders to get the current list with IDs
2. Match the reminder the user is referring to by title, time, or context
3. If genuinely ambiguous between multiple similar reminders, call ask_user to clarify
4. Call update_reminder with ONLY the fields that are changing, plus a short confirmation

- datetime format: YYYY-MM-DDTHH:MM:00
- Only include fields that actually change — omit everything else

Valid responses:
{"action": "get_reminders"}
{"action": "ask_user", "question": "..."}
{"action": "update_reminder", "id": "...", "title": "...", "datetime": "...", "location": "...", "pre_alert_minutes": 0, "follow_up_minutes": 0, "confirmation": "..."}
""" + _SHARED


DELETE_PROMPT = """You are Nudge — a smart reminder assistant. Your only job right now is to delete one or more reminders.

WORKFLOW:
1. Call get_reminders to get the current list with IDs
2. Identify the reminder(s) the user wants to delete
3. If genuinely ambiguous, call ask_user to clarify which one
4. Call delete_reminder with the correct IDs and a short confirmation

Valid responses:
{"action": "get_reminders"}
{"action": "ask_user", "question": "..."}
{"action": "delete_reminder", "ids": ["...", "..."], "confirmation": "..."}
""" + _SHARED


QUERY_PROMPT = """You are Nudge — a smart reminder assistant. Your only job right now is to answer a question about the user's schedule or history.

WORKFLOW:
1. Call get_all_reminders to get the full history — active, done, and missed
2. Think carefully about what the user is asking
3. Call answer_user with a clear, specific, friendly answer

ANSWERING GUIDE:
- "do I have gaps today?" → look at today's reminders by time, identify free windows between them
- "did I attend X / have I done X?" → check the done/missed status of that reminder
- "what do I have tomorrow?" → filter by tomorrow's date, list them with times
- "how many reminders do I have?" → count active (done=false, missed=false) ones
- Be specific with times. Keep it conversational. Don't list everything unless they asked for a list.
- If nothing matches what they asked, say so directly — don't make things up.

Valid responses:
{"action": "get_all_reminders"}
{"action": "answer_user", "text": "..."}
""" + _SHARED


_PROMPT_MAP = {
    "create": CREATE_PROMPT,
    "update": UPDATE_PROMPT,
    "delete": DELETE_PROMPT,
    "query":  QUERY_PROMPT,
}


# ─── Agent Loop ────────────────────────────────────────────────────────────────

async def _run_loop(messages: list, system: str, user_id: str, now_str: str) -> dict:
    """
    Single reusable loop used by all four workflows.
    System prompt goes in the 'system' role — not smuggled as a user message.
    Returns original messages (without system context) so the frontend
    can safely accumulate them for multi-turn conversations.
    """
    full_messages = [
        {"role": "system", "content": f"{system}\n\nCurrent date and time: {now_str}"}
    ] + messages

    try:
        for _ in range(8):   # max 8 iterations — enough for any workflow
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=full_messages,
                temperature=0
            )

            text = response.choices[0].message.content.strip()

            # Strip markdown code fences if model wraps its JSON
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()

            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                print(f"[agent] JSON parse failed: {text}")
                return {"type": "error", "text": "Sorry, I had trouble understanding that. Try again!"}

            action = data.get("action")
            full_messages.append({"role": "assistant", "content": text})

            # ── Tool dispatch ──────────────────────────────────────────────

            if action == "get_reminders":
                result = get_reminders_tool(user_id)
                full_messages.append({
                    "role": "user",
                    "content": f"Current active reminders: {json.dumps(result)}"
                })

            elif action == "get_all_reminders":
                result = get_all_reminders_tool(user_id)
                full_messages.append({
                    "role": "user",
                    "content": f"Full reminder history (including done and missed): {json.dumps(result)}"
                })

            elif action == "ask_user":
                return {
                    "type": "question",
                    "text": data.get("question", "Can you tell me a bit more?"),
                    "messages": messages   # original only — no system context
                }

            elif action == "create_reminder":
                return {
                    "type": "reminder",
                    "data": data,
                    "messages": messages
                }

            elif action == "update_reminder":
                update_reminder_tool(data, user_id)
                return {
                    "type": "updated",
                    "text": data.get("confirmation", "Done!"),
                    "messages": messages
                }

            elif action == "delete_reminder":
                delete_reminders_tool(data.get("ids", []), user_id)
                return {
                    "type": "deleted",
                    "text": data.get("confirmation", "Deleted."),
                    "messages": messages
                }

            elif action == "answer_user":
                return {
                    "type": "answer",
                    "text": data.get("text", ""),
                    "messages": messages
                }

            else:
                print(f"[agent] Unknown action returned: {action}")
                return {"type": "error", "text": "Sorry, something went wrong. Try rephrasing!"}

    except Exception as e:
        print(f"[agent] Error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return {"type": "error", "text": "Something went wrong on my end. Try again in a moment!"}

    return {"type": "error", "text": "I got a bit confused — could you try rephrasing that?"}


# ─── Entry Point ───────────────────────────────────────────────────────────────

async def run_agent(messages: list, user_id: str) -> dict:
    # Timezone from DB — no more IST hardcoding
    tz      = _get_user_tz(user_id)
    now     = datetime.now(tz)
    now_str = now.strftime("%A, %d %B %Y %I:%M %p (%Z)")

    # Classify intent from the first user message in this conversation.
    # Multi-turn follow-ups (answer to clarifying question) carry the same
    # intent implicitly, so classifying once from the first message is enough.
    first_user_msg = next(
        (m["content"] for m in messages if m.get("role") == "user"), ""
    )
    intent = _classify_intent(first_user_msg)
    system = _PROMPT_MAP.get(intent, CREATE_PROMPT)

    print(f"[agent] intent={intent} user={user_id[:8]}...")
    return await _run_loop(messages, system, user_id, now_str)
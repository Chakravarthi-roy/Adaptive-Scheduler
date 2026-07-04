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

from datetime import datetime, date, timedelta
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


# ─── Duration defaults ──────────────────────────────────────────────────────────
# Used only when a reminder has no duration_minutes stored (legacy data, or the
# user left the modal field blank). "important" is deliberately not defaulted
# here — the create workflow asks about it once instead, since it drives the
# follow-up timing. Everything else gets a silent, reasonable assumption.
_DURATION_FALLBACK = {
    "casual":  0,
    "routine": 0,
    "personal": 30,
    "health":  30,
    "important": 60,
}


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
        if action_data.get("duration_minutes") is not None:
            reminder.duration_minutes = str(action_data["duration_minutes"])
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


# ─── Query tools: gaps + history search ─────────────────────────────────────────
# These do the actual date/time computation in Python. The LLM's job is only to
# pick the tool and fill structured params (a date, a relative range, a status) —
# never to do arithmetic over raw timestamps itself.

def _reminder_duration(r) -> int | None:
    """Real duration if stored; else a type-based fallback for casual/routine
    (always safe to assume instant); None for anything else, meaning 'unknown'."""
    stored = getattr(r, "duration_minutes", None)
    if stored not in (None, ""):
        try:
            return int(stored)
        except (TypeError, ValueError):
            pass
    if r.type in ("casual", "routine"):
        return 0
    return None


def find_schedule_gaps_tool(user_id: str, date_str: str, work_start: str = "07:00", work_end: str = "18:00") -> dict:
    """
    Computes real free windows for a given day, in Python — never left to the
    LLM to infer from a raw list of timestamps.

    Returns:
      {
        "window": "07:00–18:00",
        "gaps": [{"start": "...", "end": "...", "duration_minutes": ...}, ...],
        "unknown_duration": [{"id","title","datetime","type"}, ...]  # needs a
            duration to compute precisely; treated with a fallback for now.
      }
    """
    try:
        target_date = date.fromisoformat(date_str)
    except (TypeError, ValueError):
        target_date = date.today()

    ws_h, ws_m = map(int, work_start.split(":"))
    we_h, we_m = map(int, work_end.split(":"))
    window_start = datetime.combine(target_date, datetime.min.time()).replace(hour=ws_h, minute=ws_m)
    window_end   = datetime.combine(target_date, datetime.min.time()).replace(hour=we_h, minute=we_m)

    db = SessionLocal()
    try:
        day_start = datetime.combine(target_date, datetime.min.time())
        day_end   = day_start + timedelta(days=1)
        reminders = db.query(Reminder).filter(
            Reminder.user_id == user_id,
            Reminder.datetime >= day_start,
            Reminder.datetime < day_end
        ).order_by(Reminder.datetime).all()

        busy = []
        unknown = []
        for r in reminders:
            dur = _reminder_duration(r)
            if dur is None:
                unknown.append({
                    "id": r.id, "title": r.title,
                    "datetime": r.datetime.isoformat(), "type": r.type
                })
                dur = _DURATION_FALLBACK.get(r.type, 30)  # used only to keep the gap math sane
            start = r.datetime
            end   = start + timedelta(minutes=dur)
            # clip to the working window
            start = max(start, window_start)
            end   = min(end, window_end)
            if end > start:
                busy.append((start, end))

        busy.sort()
        merged = []
        for start, end in busy:
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))

        gaps = []
        cursor = window_start
        for start, end in merged:
            if start > cursor:
                gaps.append((cursor, start))
            cursor = max(cursor, end)
        if cursor < window_end:
            gaps.append((cursor, window_end))

        gaps = [(s, e) for s, e in gaps if (e - s) >= timedelta(minutes=10)]

        return {
            "window": f"{work_start}–{work_end}",
            "gaps": [
                {
                    "start": s.strftime("%I:%M %p"),
                    "end":   e.strftime("%I:%M %p"),
                    "duration_minutes": int((e - s).total_seconds() // 60)
                }
                for s, e in gaps
            ],
            "unknown_duration": unknown
        }
    finally:
        db.close()


def _resolve_relative_range(relative: str, today: date) -> tuple[date, date] | None:
    """Turns a coarse relative label (from the LLM) into exact date bounds.
    All the actual date math lives here, once, instead of inside a prompt."""
    if relative == "today":
        return today, today
    if relative == "yesterday":
        y = today - timedelta(days=1)
        return y, y
    if relative == "this_week":
        start = today - timedelta(days=today.weekday())
        return start, today
    if relative == "last_week":
        this_start = today - timedelta(days=today.weekday())
        last_start = this_start - timedelta(days=7)
        last_end   = this_start - timedelta(days=1)
        return last_start, last_end
    if relative == "this_month":
        return today.replace(day=1), today
    if relative == "last_month":
        first_this = today.replace(day=1)
        last_end   = first_this - timedelta(days=1)
        last_start = last_end.replace(day=1)
        return last_start, last_end
    return None  # "all" / unrecognized → no date filter


def search_reminders_tool(user_id: str, query_text: str | None = None, relative_range: str | None = None,
                           status: str | None = None) -> list:
    """
    General-purpose schedule search — covers "did I attend X last week",
    "what did I do yesterday", "how many things did I mark done last month",
    all through one flexible, deterministic filter instead of a dozen
    one-off tools.
    """
    db = SessionLocal()
    try:
        q = db.query(Reminder).filter(Reminder.user_id == user_id)

        if query_text:
            q = q.filter(Reminder.title.ilike(f"%{query_text}%"))

        if relative_range:
            bounds = _resolve_relative_range(relative_range, date.today())
            if bounds:
                start_date, end_date = bounds
                start_dt = datetime.combine(start_date, datetime.min.time())
                end_dt   = datetime.combine(end_date, datetime.min.time()) + timedelta(days=1)
                q = q.filter(Reminder.datetime >= start_dt, Reminder.datetime < end_dt)

        if status == "done":
            q = q.filter(Reminder.done == True)
        elif status == "missed":
            q = q.filter(Reminder.missed == True)
        elif status == "active":
            q = q.filter(Reminder.done == False, Reminder.missed == False)

        reminders = q.order_by(Reminder.datetime).all()
        return [
            {
                "id":       r.id,
                "title":    r.title,
                "datetime": r.datetime.isoformat() if r.datetime else None,
                "type":     r.type,
                "done":     r.done,
                "missed":   getattr(r, "missed", False)
            }
            for r in reminders
        ]
    finally:
        db.close()


# ─── Workflow Prompts ──────────────────────────────────────────────────────────
# Each prompt only describes what that workflow needs — no noise from others.
# Shared formatting rules are appended to keep individual prompts short.

_SHARED = """
Respond ONLY with valid JSON — no extra text, no markdown, no code fences.
Strip filler words like ra, yaar, na, bro, da from any titles.
Be concise and conversational in any confirmation, question, or answer.
IMPORTANT: Before calling ask_user, check earlier assistant messages in this
conversation. If you already asked a clarifying question and the user's reply
didn't resolve it, DO NOT ask it again — proceed with your best reasonable
assumption instead. Never repeat the same clarifying question twice."""


CREATE_PROMPT = """You are Nudge — a smart reminder assistant. Your only job right now is to create a new reminder.

WORKFLOW:
1. Call get_reminders to see the existing schedule (resolves relative times like "after my exam")
2. Extract everything you can from what the user said and infer the rest
3. Only call ask_user if the time/date is completely missing AND cannot be inferred, OR if type is "important" and duration is genuinely unclear (see DURATION RULES) — ask about ONE thing at a time, and never ask the same question twice in this conversation
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

DURATION RULES — how long the task itself takes, in minutes:
- Extract directly if stated ("1 hour meeting" → 60, "30 min call" → 30)
- 0 for casual/routine — these have no real duration (drink water, stretch, check messages)
- For health/personal with no stated duration, estimate a reasonable default (e.g. 30) — do NOT ask, just estimate
- For type == "important" specifically: if duration is not stated and cannot be reasonably inferred from context, ask_user ONCE (e.g. "How long is the exam?"). If you already asked this in the conversation and got no clear answer, default to 60 and move on — never ask twice
- This value also drives the follow-up default below

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
- For important/health tasks where duration_minutes is known or estimated: default to duration_minutes + 10, so the nudge fires after the task likely finished rather than at a flat guess
- Default to 0 otherwise.

NEVER ask for location, participants, or other optional fields — leave them empty.

Valid responses:
{"action": "get_reminders"}
{"action": "ask_user", "question": "..."}
{"action": "create_reminder", "title": "...", "datetime": "...", "location": "", "type": "...", "repeat": "none", "participants": [], "action_label": "...", "duration_minutes": 0, "pre_alert_minutes": 0, "follow_up_minutes": 0}
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
{"action": "update_reminder", "id": "...", "title": "...", "datetime": "...", "location": "...", "duration_minutes": 0, "pre_alert_minutes": 0, "follow_up_minutes": 0, "confirmation": "..."}
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


QUERY_PROMPT = """You are Nudge — a smart reminder assistant. Your only job right now is to answer a question about the user's schedule — past, present, or free time — using tools that already computed the real answer. You never do date/time arithmetic yourself.

TOOLS:
- find_gaps: for "do I have a gap / free time / any room today". Give it a "date" (YYYY-MM-DD, resolved from words like "today"/"tomorrow"). It checks a fixed 07:00–18:00 window and returns the actual free windows already computed. If the user's own phrasing implies a different range ("free after 8pm", "gap this morning"), pass "work_start"/"work_end" to match that instead of the default.
- search_reminders: for everything else — "did I attend X", "what did I do yesterday", "how many things last month". Give it any combination of "query_text" (fuzzy title match), "relative_range" (one of: today, yesterday, this_week, last_week, this_month, last_month, all), and "status" (done, missed, active).
- get_all_reminders: only if the above two genuinely don't cover it.

GAP-ANSWER RULES:
- Always state the window you checked, e.g. "Between 7am and 6pm, you're free from 2 to 4:30."
- find_gaps may return "unknown_duration" reminders — these are ones where duration couldn't be determined, so a fallback estimate was used to compute the gaps you got back.
  - If there are 1–2 of them and their duration could meaningfully change the answer, you may ask_user about them ONCE, at most 2 at a time — never more, and never repeat a question about the same reminder if you've already asked in this conversation.
  - If there are more than 2, ask about the 2 most relevant to the question, get an answer, and proceed with fallback estimates for the rest — do not interrogate the user about every single one.
  - If the user doesn't give a clear duration when asked, proceed with the fallback and answer anyway — do not ask again.

ANSWERING GUIDE:
- Be specific with times/dates. Keep it conversational. Don't list everything unless they asked for a list.
- If nothing matches what they asked, say so directly — don't make things up.
- Alongside your narrated answer, include "items": the raw list of reminders/gaps the tools returned that back up your answer (or [] if none apply) — this is structured evidence, not for you to re-summarize, just pass through what's relevant.

Valid responses:
{"action": "find_gaps", "date": "YYYY-MM-DD", "work_start": "07:00", "work_end": "18:00"}
{"action": "search_reminders", "query_text": "...", "relative_range": "...", "status": "..."}
{"action": "get_all_reminders"}
{"action": "ask_user", "question": "..."}
{"action": "answer_user", "text": "...", "items": [...]}
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

    IMPORTANT: every return carries full_messages[1:] (the whole conversation
    minus the system prompt) — NOT the bare input `messages`. The previous
    version returned the original input only, which silently dropped the
    assistant's own tool calls, fetched data, and prior questions from the
    history sent back next turn. That meant the model had no memory of what
    it had already asked or fetched, and would re-ask the same clarifying
    question or re-fetch the same data every turn. Keeping full_messages
    intact is what lets the model recognize "I already asked this" and move
    on instead of looping.
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

            elif action == "find_gaps":
                result = find_schedule_gaps_tool(
                    user_id,
                    data.get("date"),
                    data.get("work_start", "07:00"),
                    data.get("work_end", "18:00")
                )
                full_messages.append({
                    "role": "user",
                    "content": f"Computed schedule gaps: {json.dumps(result)}"
                })

            elif action == "search_reminders":
                result = search_reminders_tool(
                    user_id,
                    query_text=data.get("query_text"),
                    relative_range=data.get("relative_range"),
                    status=data.get("status")
                )
                full_messages.append({
                    "role": "user",
                    "content": f"Search results: {json.dumps(result)}"
                })

            elif action == "ask_user":
                return {
                    "type": "question",
                    "text": data.get("question", "Can you tell me a bit more?"),
                    "messages": full_messages[1:]
                }

            elif action == "create_reminder":
                return {
                    "type": "reminder",
                    "data": data,
                    "messages": full_messages[1:]
                }

            elif action == "update_reminder":
                update_reminder_tool(data, user_id)
                return {
                    "type": "updated",
                    "text": data.get("confirmation", "Done!"),
                    "messages": full_messages[1:]
                }

            elif action == "delete_reminder":
                delete_reminders_tool(data.get("ids", []), user_id)
                return {
                    "type": "deleted",
                    "text": data.get("confirmation", "Deleted."),
                    "messages": full_messages[1:]
                }

            elif action == "answer_user":
                return {
                    "type": "answer",
                    "text": data.get("text", ""),
                    "items": data.get("items", []),
                    "messages": full_messages[1:]
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
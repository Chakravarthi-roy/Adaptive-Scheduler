"""
tools.py — the action layer

Every function here is plain, deterministic Python that touches the database.
The LLM never touches the DB directly — it only ever emits a JSON action, and
the orchestrator calls the matching function below.

Each tool catches its own exceptions and returns {"error": "..."} instead of
raising, so a single bad DB call surfaces as a clean, identifiable failure
the orchestrator can react to — not an unhandled crash of the whole request.
"""

from datetime import datetime, date, timedelta
from database import SessionLocal, Reminder
from sqlalchemy import or_
import re

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

_STOPWORDS = {
    "a", "an", "the", "i", "did", "do", "does", "attend",
    "attended", "attending", "went", "go", "going", "gone", "to",
    "for", "on", "in", "at", "have", "has", "had", "my", "this",
    "that", "of", "was", "were", "is", "are", "with", "and"
}


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
    except Exception as e:
        print(f"[tools] get_reminders_tool failed: {type(e).__name__}: {e}")
        return {"error": "Could not load reminders right now."}
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
    except Exception as e:
        print(f"[tools] get_all_reminders_tool failed: {type(e).__name__}: {e}")
        return {"error": "Could not load reminder history right now."}
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
    except Exception as e:
        print(f"[tools] update_reminder_tool failed: {type(e).__name__}: {e}")
        db.rollback()
        return {"error": "Could not save that update — please try again."}
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
    except Exception as e:
        print(f"[tools] delete_reminders_tool failed: {type(e).__name__}: {e}")
        db.rollback()
        return {"error": "Could not delete — please try again."}
    finally:
        db.close()


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
    """
    try:
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
                    dur = _DURATION_FALLBACK.get(r.type, 30)
                start = max(r.datetime, window_start)
                end   = min(r.datetime + timedelta(minutes=dur), window_end)
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
    except Exception as e:
        print(f"[tools] find_schedule_gaps_tool failed: {type(e).__name__}: {e}")
        return {"error": "Could not compute gaps right now."}


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
    try:
        db = SessionLocal()
        try:
            q = db.query(Reminder).filter(Reminder.user_id == user_id)

            if query_text:
                # Token-based OR match, not a rigid whole-phrase match. The LLM
                # might pass "attended the wedding" while the actual title is
                # "go to the wedding" — a literal substring match on the full
                # phrase would find nothing even though "wedding" matches.
                tokens = [
                    w for w in re.findall(r"[a-zA-Z0-9']+", query_text.lower())
                    if w not in _STOPWORDS and len(w) > 1
                ]
                if tokens:
                    q = q.filter(or_(*[Reminder.title.ilike(f"%{t}%") for t in tokens]))
                else:
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
    except Exception as e:
        print(f"[tools] search_reminders_tool failed: {type(e).__name__}: {e}")
        return {"error": "Could not search reminders right now."}
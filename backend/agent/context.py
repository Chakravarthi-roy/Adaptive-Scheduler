"""
context.py — per-user runtime context

Small, separate from the DB-query tools in tools.py because this isn't data
the LLM asks for mid-conversation — it's context the pipeline needs BEFORE
the LLM is even called (current time in the user's own timezone, and now
demo-cap status).
"""

from database import SessionLocal, User, Reminder
import pytz


def get_user_tz(user_id: str) -> pytz.BaseTzInfo:
    """Get user's saved timezone from DB, fall back to IST if not set or on error."""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        tz_str = getattr(user, "timezone", None) or "Asia/Kolkata"
        try:
            return pytz.timezone(tz_str)
        except pytz.UnknownTimeZoneError:
            print(f"[context] unknown timezone '{tz_str}' for user {user_id[:8]}, falling back to IST")
            return pytz.timezone("Asia/Kolkata")
    except Exception as e:
        print(f"[context] failed to load user timezone: {type(e).__name__}: {e}")
        return pytz.timezone("Asia/Kolkata")
    finally:
        db.close()


def get_demo_status(user_id: str) -> tuple[bool, int]:
    """
    Returns (is_demo, existing_reminder_count) for the given user.

    Used to short-circuit the create workflow BEFORE burning an LLM call
    (or several, across a multi-turn conversation) on a demo account that's
    already used its one allowed reminder. The actual cap is enforced as a
    hard count in reminders.py's POST /reminders — ALL reminders the demo
    user has ever created, done/missed included, not just active ones — this
    just lets the agent see that same fact ahead of time instead of finding
    out only when the user taps Save at the very end.
    """
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return False, 0
        count = db.query(Reminder).filter(Reminder.user_id == user_id).count()
        return bool(user.is_demo), count
    except Exception as e:
        print(f"[context] failed to load demo status: {type(e).__name__}: {e}")
        return False, 0
    finally:
        db.close()
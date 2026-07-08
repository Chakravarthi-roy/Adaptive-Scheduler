"""
context.py — per-user runtime context

Small, separate from the DB-query tools in tools.py because this isn't data
the LLM asks for mid-conversation — it's context the pipeline needs BEFORE
the LLM is even called (current time in the user's own timezone).
"""

from database import SessionLocal, User
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
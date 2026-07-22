from fastapi import APIRouter, HTTPException, Header, Request
from database import SessionLocal, Reminder
from auth import get_user_from_token
# from rate_limit import limiter
from datetime import datetime, timedelta
import json, uuid

router = APIRouter()


def _require_user(authorization):
    user = get_user_from_token(authorization)
    if not user:
        raise HTTPException(status_code=401, detail="Please log in")
    return user


@router.post("/reminders")
# @limiter.limit("30/minute")
def save_reminder(request: Request, data: dict, authorization: str | None = Header(default=None)):
    user = _require_user(authorization)
    db   = SessionLocal()
    try:
        # Demo users: limit to 1 reminder
        if user.is_demo:
            existing = db.query(Reminder).filter(Reminder.user_id == user.id).count()
            if existing >= 1:
                raise HTTPException(
                    status_code=403,
                    detail="Demo limit reached — create a free account to add more reminders!"
                )

        reminder = Reminder(
            id=str(uuid.uuid4()),
            user_id=user.id,
            is_demo_reminder=user.is_demo,   # flag it so owner can see it separately
            title=data.get("title", ""),
            datetime=datetime.fromisoformat(data["datetime"]) if data.get("datetime") else None,
            location=data.get("location"),
            type=data.get("type", "personal"),
            repeat=data.get("repeat", "none"),
            participants=json.dumps(data.get("participants", [])),
            action_label=data.get("action_label") or None,
            duration_minutes=data.get("duration_minutes") if data.get("duration_minutes") not in (None, "") else None,
            pre_alert_minutes=data.get("pre_alert_minutes") if data.get("pre_alert_minutes") not in (None, "") else None,
            follow_up_minutes=data.get("follow_up_minutes") if data.get("follow_up_minutes") not in (None, "") else None,
            done=False
        )
        db.add(reminder)
        db.commit()
        return {"status": "saved", "id": reminder.id}
    finally:
        db.close()


@router.get("/reminders")
def get_reminders(authorization: str | None = Header(default=None)):
    user = _require_user(authorization)
    db   = SessionLocal()
    try:
        # Admin users also see demo reminders from all users (in a different color on the frontend)
        if user.is_admin:
            reminders = db.query(Reminder).filter(
                (Reminder.user_id == user.id) | (Reminder.is_demo_reminder == True)
            ).order_by(Reminder.datetime).all()
        else:
            reminders = db.query(Reminder).filter(
                Reminder.user_id == user.id
            ).order_by(Reminder.datetime).all()

        return [
            {
                "id":               r.id,
                "title":            r.title,
                "datetime":         r.datetime.isoformat() if r.datetime else None,
                "location":         r.location,
                "type":             r.type,
                "repeat":           r.repeat,
                "participants":     json.loads(r.participants) if r.participants else [],
                "duration_minutes": r.duration_minutes if hasattr(r, "duration_minutes") else None,
                "done":             r.done,
                "missed":           r.missed if hasattr(r, "missed") else False,
                "is_demo_reminder": r.is_demo_reminder if hasattr(r, "is_demo_reminder") else False
            }
            for r in reminders
        ]
    finally:
        db.close()


@router.post("/reminders/{reminder_id}/snooze")
def snooze_reminder(reminder_id: str, authorization: str | None = Header(default=None)):
    user = _require_user(authorization)
    db   = SessionLocal()
    try:
        reminder = db.query(Reminder).filter(
            Reminder.id == reminder_id,
            Reminder.user_id == user.id
        ).first()
        if reminder and reminder.datetime:
            reminder.datetime    = reminder.datetime + timedelta(minutes=10)
            reminder.notified    = False
            reminder.pre_alerted = False
            db.commit()
            return {"status": "snoozed"}
        return {"status": "not found"}
    finally:
        db.close()


@router.patch("/reminders/{reminder_id}/done")
def mark_done(reminder_id: str, authorization: str | None = Header(default=None)):
    user = _require_user(authorization)
    db   = SessionLocal()
    try:
        if user.is_admin:
            reminder = db.query(Reminder).filter(
                Reminder.id == reminder_id,
                (Reminder.user_id == user.id) | (Reminder.is_demo_reminder == True)
            ).first()
        else:
            reminder = db.query(Reminder).filter(
                Reminder.id == reminder_id,
                Reminder.user_id == user.id
            ).first()
        if not reminder:
            return {"status": "not found"}

        if reminder.repeat == "daily" and reminder.datetime:
            reminder.datetime       = reminder.datetime + timedelta(days=1)
            reminder.notified       = False
            reminder.pre_alerted    = False
            reminder.follow_up_sent = False
        elif reminder.repeat == "weekly" and reminder.datetime:
            reminder.datetime       = reminder.datetime + timedelta(weeks=1)
            reminder.notified       = False
            reminder.pre_alerted    = False
            reminder.follow_up_sent = False
        else:
            reminder.done = True

        db.commit()
        return {"status": "marked done"}
    finally:
        db.close()
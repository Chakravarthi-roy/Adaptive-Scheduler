from fastapi import APIRouter
from database import SessionLocal, Reminder
from datetime import datetime, timedelta
import json, uuid

router = APIRouter()


@router.post("/reminders")
def save_reminder(data: dict):
    db = SessionLocal()
    try:
        reminder = Reminder(
            id=str(uuid.uuid4()),
            title=data.get("title", ""),
            datetime=datetime.fromisoformat(data["datetime"]) if data.get("datetime") else None,
            location=data.get("location"),
            type=data.get("type", "casual"),
            repeat=data.get("repeat", "none"),
            participants=json.dumps(data.get("participants", [])),
            action_label=data.get("action_label") or None,
            pre_alert_minutes=data.get("pre_alert_minutes") if data.get("pre_alert_minutes") else None,
            follow_up_minutes=data.get("follow_up_minutes") if data.get("follow_up_minutes") else None,
            done=False
        )
        db.add(reminder)
        db.commit()
        return {"status": "saved", "id": reminder.id}
    finally:
        db.close()


@router.get("/reminders")
def get_reminders():
    db = SessionLocal()
    try:
        reminders = db.query(Reminder).order_by(Reminder.datetime).all()
        return [
            {
                "id": r.id,
                "title": r.title,
                "datetime": r.datetime.isoformat() if r.datetime else None,
                "location": r.location,
                "type": r.type,
                "repeat": r.repeat,
                "participants": json.loads(r.participants) if r.participants else [],
                "done": r.done,
                "missed": r.missed if hasattr(r, "missed") else False
            }
            for r in reminders
        ]
    finally:
        db.close()


@router.post("/reminders/{reminder_id}/snooze")
def snooze_reminder(reminder_id: str):
    db = SessionLocal()
    try:
        reminder = db.query(Reminder).filter(Reminder.id == reminder_id).first()
        if reminder and reminder.datetime:
            reminder.datetime   = reminder.datetime + timedelta(minutes=10)
            reminder.notified   = False
            reminder.pre_alerted = False
            db.commit()
            return {"status": "snoozed"}
        return {"status": "not found"}
    finally:
        db.close()


@router.patch("/reminders/{reminder_id}/done")
def mark_done(reminder_id: str):
    db = SessionLocal()
    try:
        reminder = db.query(Reminder).filter(Reminder.id == reminder_id).first()
        if not reminder:
            return {"status": "not found"}

        if reminder.repeat == "daily" and reminder.datetime:
            # don't mark done — push to next day and reset flags
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
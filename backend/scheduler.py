import schedule
import time
import json
import pytz
from database import SessionLocal, Reminder
from datetime import datetime, timedelta
from main import send_notification

IST = pytz.timezone('Asia/Kolkata')

def check_reminders():
    db = SessionLocal()
    try:
        now = datetime.now(IST).replace(tzinfo=None)
        window_start = now - timedelta(seconds=30)
        window_end = now + timedelta(seconds=30)

        due = db.query(Reminder).filter(
            Reminder.done == False,
            Reminder.notified == False,
            Reminder.datetime >= window_start,
            Reminder.datetime <= window_end
        ).all()

        for reminder in due:
            body = reminder.datetime.strftime("%I:%M %p")
            if reminder.location:
                body += f" · {reminder.location}"

            persistent = reminder.type == "medication"

            result = send_notification(
                f"🔔 {reminder.title}",
                body,
                persistent
            )

            if result.get("status") == "sent":
                reminder.notified = True

                if reminder.repeat == "daily":
                    reminder.datetime = reminder.datetime + timedelta(days=1)
                    reminder.notified = False
                elif reminder.repeat == "weekly":
                    reminder.datetime = reminder.datetime + timedelta(weeks=1)
                    reminder.notified = False

        db.commit()
        print(f"[{now.strftime('%H:%M:%S')}] checked reminders — {len(due)} fired")

    finally:
        db.close()

schedule.every(1).minutes.do(check_reminders)

print("scheduler running...")
while True:
    schedule.run_pending()
    time.sleep(10)
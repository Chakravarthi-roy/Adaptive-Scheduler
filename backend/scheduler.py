import schedule
import time
import json
import pytz
from database import SessionLocal, Reminder
from datetime import datetime, timedelta
from main import send_notification

IST = pytz.timezone('Asia/Kolkata')

# ─── Pre-alert config by type ─────────────────────────────────────────────────
PRE_ALERT_MINUTES = {
    "medication": 1,
    "meeting":    30,
    "task":       20,
    "casual":     0   # on time, no pre-alert
}

# ─── Button labels by type ────────────────────────────────────────────────────
ACTION_LABELS = {
    "medication": {"action": "took_it", "label": "Took it 💊"},
    "meeting": {"action": "started", "label": "Started 📅"},
    "task": {"action": "doing", "label": "Doing it ✅"},
    "casual": {"action": "done", "label": "Done ✓"}
}

# ─── Notification content by type ────────────────────────────────────────────
def build_notification(reminder, is_pre_alert=False):
    title = reminder.title
    time_str = reminder.datetime.strftime("%I:%M %p")
    location_str = f" · {reminder.location}" if reminder.location else ""
    
    # Get action and label for this type
    action_config = ACTION_LABELS.get(reminder.type, ACTION_LABELS["casual"])
    action = action_config["action"]
    action_label = action_config["label"]
    
    # Determine persistence based on type
    persistent = reminder.type == "medication"

    if is_pre_alert:
        minutes = PRE_ALERT_MINUTES[reminder.type]
        if reminder.type == "medication":
            return {
                "title": f"💊 {title} in {minutes} min",
                "body": f"Get your medication ready · {time_str}",
                "action": action,
                "action_label": action_label,
                "persistent": persistent,
                "sound": True
            }
        elif reminder.type == "meeting":
            return {
                "title": f"📅 {title} in {minutes} mins",
                "body": f"Meeting coming up at {time_str}{location_str}",
                "action": action,
                "action_label": action_label,
                "persistent": persistent,
                "sound": True
            }
        elif reminder.type == "task":
            return {
                "title": f"📝 {title} in {minutes} mins",
                "body": f"Starting at {time_str}{location_str}",
                "action": action,
                "action_label": action_label,
                "persistent": persistent,
                "sound": True
            }
        else:  # casual — no pre-alert
            return None
    else:
        # on-time notification
        if reminder.type == "medication":
            return {
                "title": f"💊 {title}",
                "body": f"Time to take your medication · {time_str}",
                "action": action,
                "action_label": action_label,
                "persistent": persistent,
                "sound": True
            }
        elif reminder.type == "meeting":
            return {
                "title": f"📅 {title}",
                "body": f"Your meeting is now · {time_str}{location_str}",
                "action": action,
                "action_label": action_label,
                "persistent": persistent,
                "sound": True
            }
        elif reminder.type == "task":
            return {
                "title": f"📝 {title}",
                "body": f"Time to start · {time_str}{location_str}",
                "action": action,
                "action_label": action_label,
                "persistent": persistent,
                "sound": True
            }
        elif reminder.type == "casual":
            return {
                "title": f"🔔 {title}",
                "body": time_str,
                "action": action,
                "action_label": action_label,
                "persistent": persistent,
                "sound": True
            }

    return {
        "title": f"🔔 {title}",
        "body": time_str,
        "action": action,
        "action_label": action_label,
        "persistent": persistent,
        "sound": True
    }


def check_reminders():
    db = SessionLocal()
    try:
        now = datetime.now(IST).replace(tzinfo=None)
        window_start = now - timedelta(seconds=30)
        window_end = now + timedelta(seconds=30)

        pre_alerted_count = 0
        notified_count = 0

        # ── 1. Check pre-alerts ───────────────────────────────────────────────
        for reminder_type, minutes in PRE_ALERT_MINUTES.items():
            if minutes == 0:
                continue  # casual — no pre-alert

            pre_alert_window_start = window_start + timedelta(minutes=minutes)
            pre_alert_window_end = window_end + timedelta(minutes=minutes)

            due_pre = db.query(Reminder).filter(
                Reminder.done == False,
                Reminder.notified == False,
                Reminder.pre_alerted == False,
                Reminder.type == reminder_type,
                Reminder.datetime >= pre_alert_window_start,
                Reminder.datetime <= pre_alert_window_end
            ).all()

            for reminder in due_pre:
                notif = build_notification(reminder, is_pre_alert=True)
                result = send_notification(
                    notif["title"],
                    notif["body"],
                    notif["persistent"],
                    action=notif["action"],
                    action_label=notif["action_label"],
                    reminder_id=reminder.id
                )
                if result.get("status") == "sent":
                    reminder.pre_alerted = True
                    pre_alerted_count += 1

        # ── 2. Check on-time notifications ────────────────────────────────────
        due = db.query(Reminder).filter(
            Reminder.done == False,
            Reminder.notified == False,
            Reminder.datetime >= window_start,
            Reminder.datetime <= window_end
        ).all()

        for reminder in due:
            notif = build_notification(reminder, is_pre_alert=False)
            result = send_notification(
                notif["title"],
                notif["body"],
                notif["persistent"],
                action=notif["action"],
                action_label=notif["action_label"],
                reminder_id=reminder.id
            )

            if result.get("status") == "sent":
                reminder.notified = True
                notified_count += 1

                # handle recurring
                if reminder.repeat == "daily":
                    reminder.datetime = reminder.datetime + timedelta(days=1)
                    reminder.notified = False
                    reminder.pre_alerted = False
                elif reminder.repeat == "weekly":
                    reminder.datetime = reminder.datetime + timedelta(weeks=1)
                    reminder.notified = False
                    reminder.pre_alerted = False

        db.commit()
        print(f"[{now.strftime('%H:%M:%S')}] checked — {pre_alerted_count} pre-alerts, {notified_count} fired")

    finally:
        db.close()


schedule.every(1).minutes.do(check_reminders)

print("scheduler running...")
while True:
    schedule.run_pending()
    time.sleep(10)
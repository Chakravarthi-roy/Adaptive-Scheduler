import pytz
from database import SessionLocal, Reminder
from datetime import datetime, timedelta
from notification import send_notification

IST = pytz.timezone('Asia/Kolkata')

# Pre-alert and follow-up are now stored per-reminder (set by agent)
# These are fallback defaults only for reminders created before this change
FALLBACK_PRE_ALERT = {
    "medication": 5,
    "meeting":    20,
    "task":       15,
    "casual":     0
}

# ─── Fallback button labels (used when no custom label stored on reminder) ────
_DEFAULT_LABELS = {
    "medication": {"action": "took_it",  "label": "Took it 💊"},
    "meeting":    {"action": "started",  "label": "Started 📅"},
    "task":       {"action": "doing",    "label": "Doing it ✓"},
    "casual":     {"action": "done",     "label": "Done ✓"},
}

def get_action_config(reminder):
    custom = getattr(reminder, "action_label", None)
    default = _DEFAULT_LABELS.get(reminder.type, _DEFAULT_LABELS["casual"])
    label = custom if custom else default["label"]
    return default["action"], label

# ─── Notification content by type ────────────────────────────────────────────
def build_notification(reminder, is_pre_alert=False):
    title = reminder.title
    time_str = reminder.datetime.strftime("%I:%M %p")
    location_str = f" · {reminder.location}" if reminder.location else ""
    action, action_label = get_action_config(reminder)
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

        # ── 1. Check pre-alerts (dynamic per-reminder) ──────────────────────
        # fetch all unnotified, un-pre-alerted reminders with a datetime set
        candidates = db.query(Reminder).filter(
            Reminder.done == False,
            Reminder.notified == False,
            Reminder.pre_alerted == False,
            Reminder.datetime != None
        ).all()

        for reminder in candidates:
            # get pre_alert_minutes — use stored value, fallback to type default
            stored = getattr(reminder, 'pre_alert_minutes', None)
            if stored is not None:
                try:
                    minutes = int(stored)
                except:
                    minutes = 0
            else:
                minutes = FALLBACK_PRE_ALERT.get(reminder.type, 0)

            if minutes == 0:
                continue

            pre_alert_window_start = window_start + timedelta(minutes=minutes)
            pre_alert_window_end   = window_end   + timedelta(minutes=minutes)

            if not (pre_alert_window_start <= reminder.datetime <= pre_alert_window_end):
                continue

            notif = build_notification(reminder, is_pre_alert=True)
            result = send_notification(
                notif["title"],
                notif["body"],
                notif["persistent"],
                action=notif["action"],
                action_label=notif["action_label"],
                reminder_id=reminder.id,
                is_pre_alert=True
            )
            if result.get("status") == "sent":
                reminder.pre_alerted = True
                pre_alerted_count += 1

        # ── 2. Check on-time notifications — catch overdue too ───────────────
        due = db.query(Reminder).filter(
            Reminder.done == False,
            Reminder.notified == False,
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

        # ── 3. Check follow-ups ───────────────────────────────────────────────
        followup_count = 0
        followup_candidates = db.query(Reminder).filter(
            Reminder.done == False,
            Reminder.notified == True,
            Reminder.follow_up_sent == False,
            Reminder.datetime != None
        ).all()

        for reminder in followup_candidates:
            stored = getattr(reminder, 'follow_up_minutes', None)
            if stored is None:
                continue
            try:
                fu_minutes = int(stored)
            except:
                continue
            if fu_minutes == 0:
                continue

            followup_time = reminder.datetime + timedelta(minutes=fu_minutes)
            if not (window_start <= followup_time <= window_end):
                continue

            from notification import build_followup_notification
            notif = build_followup_notification(reminder)
            result = send_notification(
                notif["title"],
                notif["body"],
                notif["persistent"],
                action=notif["action"],
                action_label=notif["action_label"],
                reminder_id=reminder.id,
                is_pre_alert=False
            )
            if result.get("status") == "sent":
                reminder.follow_up_sent = True
                followup_count += 1

        db.commit()
        print(f"[{now.strftime('%H:%M:%S')}] checked — {pre_alerted_count} pre-alerts, {notified_count} fired, {followup_count} follow-ups")

    finally:
        db.close()


# schedule.every(1).minutes.do(check_reminders)

# print("scheduler running...")
# while True:
#     schedule.run_pending()
#     time.sleep(10)
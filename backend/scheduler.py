import pytz
from database import SessionLocal, Reminder
from datetime import datetime, timedelta
from notification import send_notification

IST = pytz.timezone('Asia/Kolkata')

# Pre-alert fallback for reminders created before dynamic timing existed
FALLBACK_PRE_ALERT = {
    "important": 20,
    "health":    5,
    "routine":   10,
    "personal":  5,
    "casual":    0
}

# Emoji + generic fallback action label per type (used only if agent didn't set a custom action_label)
_TYPE_META = {
    "important": {"emoji": "❗", "action": "done",  "label": "Done ✓"},
    "health":    {"emoji": "💊", "action": "done",  "label": "Done ✓"},
    "routine":   {"emoji": "🔁", "action": "done",  "label": "Done ✓"},
    "personal":  {"emoji": "📌", "action": "done",  "label": "Done ✓"},
    "casual":    {"emoji": "🔔", "action": "done",  "label": "Done ✓"},
}

def get_action_config(reminder):
    custom = getattr(reminder, "action_label", None)
    meta = _TYPE_META.get(reminder.type, _TYPE_META["personal"])
    label = custom if custom else meta["label"]
    return meta["action"], label

# ─── Notification content — generic, works for any type ──────────────────────
def build_notification(reminder, is_pre_alert=False):
    title = reminder.title
    time_str = reminder.datetime.strftime("%I:%M %p")
    location_str = f" · {reminder.location}" if reminder.location else ""
    action, action_label = get_action_config(reminder)
    meta = _TYPE_META.get(reminder.type, _TYPE_META["personal"])
    persistent = reminder.type == "health"

    if is_pre_alert:
        minutes = int(reminder.pre_alert_minutes) if reminder.pre_alert_minutes else FALLBACK_PRE_ALERT.get(reminder.type, 0)
        return {
            "title": f"{meta['emoji']} {title} in {minutes} min",
            "body": f"Coming up at {time_str}{location_str}",
            "action": action,
            "action_label": action_label,
            "persistent": persistent,
            "sound": True
        }
    else:
        return {
            "title": f"{meta['emoji']} {title}",
            "body": f"Now · {time_str}{location_str}" if reminder.location else time_str,
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
                is_pre_alert=True,
                user_id=reminder.user_id
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
                reminder_id=reminder.id,
                user_id=reminder.user_id
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

        # ── 3. Check missed — notified but no action after 60 min ──────────
        missed_count = 0
        missed_candidates = db.query(Reminder).filter(
            Reminder.done == False,
            Reminder.missed == False,
            Reminder.notified == True,
            Reminder.datetime != None
        ).all()

        for reminder in missed_candidates:
            # skip if follow_up hasn't fired yet — let follow-up handle it first
            if reminder.follow_up_minutes and not reminder.follow_up_sent:
                continue
            missed_threshold = reminder.datetime + timedelta(minutes=60)
            if now >= missed_threshold:
                reminder.missed = True
                missed_count += 1
                # re-fire as missed notification
                send_notification(
                    f"Missed: {reminder.title}",
                    "You didn't action this reminder",
                    persistent=True,
                    action=reminder.action_label or "done",
                    action_label="Done now ✓",
                    reminder_id=reminder.id,
                    is_pre_alert=False,
                    user_id=reminder.user_id
                )
        if missed_count:
            db.commit()

        # ── 4. Check follow-ups ───────────────────────────────────────────────
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
                is_pre_alert=False,
                user_id=reminder.user_id
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
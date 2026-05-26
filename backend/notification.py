import json
import pytz
from pywebpush import webpush, WebPushException
from database import SessionLocal, PushSubscription
import os

VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY")
VAPID_EMAIL = os.getenv("VAPID_EMAIL")

# ─── Fallback button labels by type (used when no custom label is stored) ────
_DEFAULT_LABELS = {
    "medication": {"action": "took_it",  "label": "Took it 💊"},
    "meeting":    {"action": "started",  "label": "Started 📅"},
    "task":       {"action": "doing",    "label": "Doing it ✓"},
    "casual":     {"action": "done",     "label": "Done ✓"},
}

def get_action_config(reminder):
    """Return (action_key, label) — uses reminder.action_label if set, else type default."""
    custom = getattr(reminder, 'action_label', None)
    default = _DEFAULT_LABELS.get(reminder.type, _DEFAULT_LABELS["casual"])
    label = custom if custom else default["label"]
    return default["action"], label

# ─── Pre-alert config by type ─────────────────────────────────────────────────
PRE_ALERT_MINUTES = {
    "medication": 1,
    "meeting":    30,
    "task":       20,
    "casual":     0
}

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
        else:
            return None
    else:
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

def send_notification(title, body, persistent=False, action=None, action_label=None, reminder_id=None, is_pre_alert=False, vibrate=True):
    db = SessionLocal()
    try:
        sub = db.query(PushSubscription).first()
        if not sub:
            return {"status": "no subscription found"}
        subscription = json.loads(sub.subscription_json)

        payload = {
            "title": title,
            "body": body,
            "persistent": persistent,
            "reminder_id": reminder_id,
            "is_pre_alert": is_pre_alert,
            "sound": vibrate   # sw.js uses this to control vibration
        }

        if action and action_label:
            payload["action"] = action
            payload["action_label"] = action_label

        webpush(
            subscription_info=subscription,
            data=json.dumps(payload),
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={"sub": VAPID_EMAIL}
        )
        return {"status": "sent"}
    except WebPushException as ex:
        print("push failed:", ex)
        return {"status": "failed", "error": str(ex)}
    finally:
        db.close()
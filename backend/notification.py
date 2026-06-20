import json
import pytz
from pywebpush import webpush, WebPushException
from database import SessionLocal, PushSubscription
import os

VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY")
VAPID_EMAIL = os.getenv("VAPID_EMAIL")

# Notification content building (build_notification, get_action_config) lives in
# scheduler.py — this file only handles delivery (send_notification) and the
# simple follow-up message.

def build_followup_notification(reminder):
    """Simple follow-up nudge — did you do it?"""
    return {
        "title": f"Did you do it? 🔔",
        "body": reminder.title,
        "action": "done",
        "action_label": "Yes, done ✓",
        "persistent": False,
        "sound": True,
        "is_pre_alert": False
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
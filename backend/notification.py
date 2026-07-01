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

def send_notification(title, body, persistent=False, action=None, action_label=None, reminder_id=None, is_pre_alert=False, vibrate=True, user_id=None):
    db = SessionLocal()
    try:
        query = db.query(PushSubscription)
        if user_id:
            query = query.filter(PushSubscription.user_id == user_id)
        subs = query.all()
        if not subs:
            return {"status": "no subscription found"}

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

        sent_count = 0
        last_error = None

        # Send to every device this user has subscribed from — not just the first
        for sub_row in subs:
            try:
                subscription = json.loads(sub_row.subscription_json)
                webpush(
                    subscription_info=subscription,
                    data=json.dumps(payload),
                    vapid_private_key=VAPID_PRIVATE_KEY,
                    vapid_claims={"sub": VAPID_EMAIL},
                    ttl=86400   # 24h — push server holds & delivers when device comes back online
                )
                sent_count += 1
            except WebPushException as ex:
                print("push failed for one subscription:", ex)
                last_error = str(ex)
                # If the subscription is dead (expired/unsubscribed), clean it up
                if ex.response is not None and ex.response.status_code in (404, 410):
                    db.delete(sub_row)

        db.commit()

        if sent_count > 0:
            return {"status": "sent", "devices": sent_count}
        return {"status": "failed", "error": last_error}
    finally:
        db.close()
from fastapi import APIRouter
from database import SessionLocal, PushSubscription
from notification import send_notification
import json, uuid

router = APIRouter()

@router.post("/subscribe")
def subscribe(data: dict):
    db = SessionLocal()
    try:
        db.query(PushSubscription).delete()
        sub = PushSubscription(
            id=str(uuid.uuid4()),
            subscription_json=json.dumps(data)
        )
        db.add(sub)
        db.commit()
        return {"status": "subscribed"}
    finally:
        db.close()


@router.get("/send-test-notification")
@router.post("/send-test-notification")
def send_test():
    return send_notification(
        "Test Notification 🔔",
        "Your Adaptive Scheduler notifications are working!"
    )
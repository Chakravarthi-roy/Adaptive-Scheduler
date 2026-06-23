from fastapi import APIRouter, HTTPException, Header
from database import SessionLocal, PushSubscription
from auth import get_user_from_token
from notification import send_notification
import json, uuid

router = APIRouter()


@router.post("/subscribe")
def subscribe(data: dict, authorization: str | None = Header(default=None)):
    user = get_user_from_token(authorization)
    if not user:
        raise HTTPException(status_code=401, detail="Please log in")

    db = SessionLocal()
    try:
        # remove this user's old subscription, keep others intact
        db.query(PushSubscription).filter(PushSubscription.user_id == user.id).delete()
        sub = PushSubscription(
            id=str(uuid.uuid4()),
            user_id=user.id,
            subscription_json=json.dumps(data)
        )
        db.add(sub)
        db.commit()
        return {"status": "subscribed"}
    finally:
        db.close()


@router.get("/send-test-notification")
@router.post("/send-test-notification")
def send_test(authorization: str | None = Header(default=None)):
    user = get_user_from_token(authorization)
    if not user:
        raise HTTPException(status_code=401, detail="Please log in")
    return send_notification(
        "Test Notification 🔔",
        "Your Adaptive Scheduler notifications are working!",
        user_id=user.id
    )

from fastapi import APIRouter, HTTPException, Header, Request
from database import SessionLocal, PushSubscription
from auth import get_user_from_token
from notification import send_notification
# from rate_limit import limiter
import json, uuid

router = APIRouter()

@router.post("/subscribe")
# @limiter.limit("10/minute")
def subscribe(request: Request, data: dict, authorization: str | None = Header(default=None)):
    user = get_user_from_token(authorization)
    if not user:
        raise HTTPException(status_code=401, detail="Please log in")

    endpoint = data.get("endpoint")
    if not endpoint:
        raise HTTPException(status_code=400, detail="Invalid subscription — missing endpoint")

    db = SessionLocal()
    try:
        # A device's push endpoint is unique per browser install. Check if this
        # exact device already has a subscription saved (e.g. they reopened the
        # app) — update it in place. Otherwise add it as a new device, leaving
        # this user's other devices (phone, laptop, etc.) untouched.
        existing_subs = db.query(PushSubscription).filter(PushSubscription.user_id == user.id).all()

        for row in existing_subs:
            try:
                existing_data = json.loads(row.subscription_json)
            except (json.JSONDecodeError, TypeError):
                continue
            if existing_data.get("endpoint") == endpoint:
                row.subscription_json = json.dumps(data)
                db.commit()
                return {"status": "subscribed", "devices": len(existing_subs)}

        sub = PushSubscription(
            id=str(uuid.uuid4()),
            user_id=user.id,
            subscription_json=json.dumps(data)
        )
        db.add(sub)
        db.commit()
        return {"status": "subscribed", "devices": len(existing_subs) + 1}
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
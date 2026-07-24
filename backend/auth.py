from fastapi import APIRouter, HTTPException, Header
from database import SessionLocal, User, Reminder, PushSubscription
from datetime import datetime, timedelta
import bcrypt, uuid

router = APIRouter()

# How long a demo account is allowed to live before cleanup claims it
DEMO_USER_TTL_HOURS = 12





# ─── Password helpers ──────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


# ─── Session helpers ───────────────────────────────────────────────────────────

def create_session(user_id: str) -> str:
    from database import Session as SessionModel
    db = SessionLocal()
    try:
        token   = str(uuid.uuid4())
        session = SessionModel(token=token, user_id=user_id, created_at=datetime.utcnow())
        db.add(session)
        db.commit()
        return token
    finally:
        db.close()


def get_user_from_token(authorization: str | None):
    """Resolve a user from the Authorization header. Returns None if invalid/missing."""
    if not authorization:
        return None
    token = authorization.replace("Bearer ", "").strip()
    if not token:
        return None
    from database import Session as SessionModel
    db = SessionLocal()
    try:
        session = db.query(SessionModel).filter(SessionModel.token == token).first()
        if not session:
            return None
        user = db.query(User).filter(User.id == session.user_id).first()
        return user
    finally:
        db.close()


# ─── Demo cleanup ───────────────────────────────────────────────────────────────
# Runs automatically every time someone starts a new demo (lazy cleanup —
# no separate cron job needed). Demo users older than DEMO_USER_TTL_HOURS
# get removed. If they made a reminder AND an admin account exists, the
# reminder is reassigned to the admin first (kept as a record, tagged
# is_demo_reminder). If there's no admin account, the reminder is just
# deleted along with the demo user — it's throwaway test data either way,
# and there's nowhere meaningful to reassign it to.
#
# NOTE: previously, if no admin account existed, demo users WITH a reminder
# were skipped entirely (never deleted) — since nearly every demo user
# creates the one reminder demo mode allows, this meant demo accounts were
# effectively never cleaned up in practice. Fixed below.

def _cleanup_old_demo_users(db):
    from database import Session as SessionModel

    cutoff = datetime.utcnow() - timedelta(hours=DEMO_USER_TTL_HOURS)
    old_demo_users = db.query(User).filter(
        User.is_demo == True,
        User.created_at < cutoff
    ).all()

    if not old_demo_users:
        return

    admin = db.query(User).filter(User.is_admin == True).first()

    for demo_user in old_demo_users:
        reminders = db.query(Reminder).filter(Reminder.user_id == demo_user.id).all()

        if reminders:
            if admin:
                for r in reminders:
                    r.user_id = admin.id
            else:
                for r in reminders:
                    db.delete(r)

        db.query(SessionModel).filter(SessionModel.user_id == demo_user.id).delete()
        db.query(PushSubscription).filter(PushSubscription.user_id == demo_user.id).delete()
        db.delete(demo_user)

    db.commit()


def run_demo_cleanup():
    """
    Public entry point for cleanup, used by the cron job (main.py) so demo
    users get purged automatically on a schedule — not just lazily, only
    when someone happens to start a NEW demo session. Opens and closes its
    own DB session since this is called independently of a request.
    """
    db = SessionLocal()
    try:
        _cleanup_old_demo_users(db)
    finally:
        db.close()


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.post("/signup")
def signup(data: dict):
    email      = (data.get("email") or "").strip().lower()
    password   = data.get("password") or ""
    nickname   = (data.get("nickname") or "").strip() or None
    demo_token = data.get("demo_token") or None

    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Please enter a valid email")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            raise HTTPException(status_code=400, detail="An account with this email already exists")

        user = User(
            id=str(uuid.uuid4()),
            email=email,
            password_hash=hash_password(password),
            nickname=nickname,
            created_at=datetime.utcnow(),
            is_demo=False
        )
        db.add(user)
        db.commit()

        if demo_token:
            from database import Session as SessionModel
            demo_session = db.query(SessionModel).filter(SessionModel.token == demo_token).first()
            if demo_session:
                db.query(SessionModel).filter(SessionModel.token == demo_token).delete()
                db.commit()

        token = create_session(user.id)
        return {"token": token, "nickname": user.nickname, "email": user.email}
    finally:
        db.close()


@router.post("/login")
def login(data: dict):
    email    = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if not user or not verify_password(password, user.password_hash):
            raise HTTPException(status_code=401, detail="Incorrect email or password")

        token = create_session(user.id)
        return {"token": token, "nickname": user.nickname, "email": user.email}
    finally:
        db.close()


@router.get("/me")
def me(authorization: str | None = Header(default=None)):
    user = get_user_from_token(authorization)
    if not user:
        raise HTTPException(status_code=401, detail="Not logged in")
    return {
        "nickname": user.nickname,
        "email": user.email,
        "is_demo": user.is_demo,
        "vibration_enabled": user.vibration_enabled if user.vibration_enabled is not None else True
    }


@router.patch("/me/settings")
def update_settings(data: dict, authorization: str | None = Header(default=None)):
    """
    Generic per-user settings update. Currently handles vibration_enabled;
    structured to accept other synced preferences (e.g. timezone) later
    without needing a new endpoint each time.
    """
    user = get_user_from_token(authorization)
    if not user:
        raise HTTPException(status_code=401, detail="Not logged in")

    db = SessionLocal()
    try:
        db_user = db.query(User).filter(User.id == user.id).first()
        if "vibration_enabled" in data:
            db_user.vibration_enabled = bool(data["vibration_enabled"])
        db.commit()
        return {"status": "ok"}
    finally:
        db.close()


@router.post("/demo")
def create_demo():
    db = SessionLocal()
    try:
        _cleanup_old_demo_users(db)

        demo_user = User(
            id=str(uuid.uuid4()),
            email=f"demo_{uuid.uuid4().hex[:10]}@demo.local",
            password_hash="",
            nickname="Demo",
            created_at=datetime.utcnow(),
            is_demo=True
        )
        db.add(demo_user)
        db.commit()
        token = create_session(demo_user.id)
        return {"token": token, "nickname": "Demo"}
    finally:
        db.close()


@router.post("/forgot-password")
def forgot_password(data: dict):
    email = (data.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Please enter your email")

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        # Always return success even if email not found — prevents user enumeration
        if not user or user.is_demo:
            return {"status": "ok"}

        import secrets
        from email_sender import send_reset_email
        import os

        token   = secrets.token_urlsafe(32)
        expires = datetime.utcnow() + timedelta(minutes=30)

        user.reset_token         = token
        user.reset_token_expires = expires
        db.commit()

        frontend_url = os.getenv("FRONTEND_URL", "").rstrip("/")
        send_reset_email(email, token, frontend_url)

        return {"status": "ok"}
    finally:
        db.close()


@router.post("/reset-password")
def reset_password(data: dict):
    token    = (data.get("token") or "").strip()
    password = data.get("password") or ""

    if not token:
        raise HTTPException(status_code=400, detail="Invalid reset link")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.reset_token == token).first()

        if not user:
            raise HTTPException(status_code=400, detail="Invalid or expired reset link")
        if user.reset_token_expires < datetime.utcnow():
            raise HTTPException(status_code=400, detail="Reset link has expired — please request a new one")

        user.password_hash       = hash_password(password)
        user.reset_token         = None
        user.reset_token_expires = None
        db.commit()

        return {"status": "ok"}
    finally:
        db.close()
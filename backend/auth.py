from fastapi import APIRouter, HTTPException, Request, Header
from database import SessionLocal, User, Reminder, PushSubscription
from datetime import datetime, timedelta
import bcrypt, uuid, time

router = APIRouter()

# ─── Rate limiter — max 5 attempts per IP per 15 min ──────────────────────────
_attempts   = {}
RATE_LIMIT  = 5
RATE_WINDOW = 15 * 60

# How long a demo account is allowed to live before cleanup claims it
DEMO_USER_TTL_HOURS = 24


def _check_rate_limit(ip: str):
    now      = time.time()
    attempts = _attempts.get(ip, [])
    attempts = [t for t in attempts if now - t < RATE_WINDOW]
    if len(attempts) >= RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Too many attempts. Please wait 15 minutes and try again.")
    attempts.append(now)
    _attempts[ip] = attempts


def _get_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


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
# get removed. If they made a reminder, it's reassigned to the admin account
# first (kept as a record, tagged is_demo_reminder) before the throwaway
# demo account is deleted.

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
                # Reassign their reminder(s) to the admin account — keeps the
                # record, is_demo_reminder flag was already set at creation
                for r in reminders:
                    r.user_id = admin.id
            else:
                # No admin configured yet — can't safely reassign, skip this
                # user for now rather than orphan or delete their reminder
                continue

        # Clean up the demo user's sessions and push subscriptions, then the user itself
        db.query(SessionModel).filter(SessionModel.user_id == demo_user.id).delete()
        db.query(PushSubscription).filter(PushSubscription.user_id == demo_user.id).delete()
        db.delete(demo_user)

    db.commit()


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.post("/signup")
def signup(data: dict, request: Request):
    _check_rate_limit(_get_ip(request))

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

        # ── Clean up demo session only — demo reminders stay where they are.
        # They get claimed by the admin account during the next cleanup pass,
        # not transferred to this new user's account.
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
def login(data: dict, request: Request):
    _check_rate_limit(_get_ip(request))

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
    return {"nickname": user.nickname, "email": user.email, "is_demo": user.is_demo}


@router.post("/demo")
def create_demo():
    """Creates a temporary demo user. Their reminder is flagged is_demo_reminder=True.
    Old demo users (24h+) are cleaned up automatically on each call — their
    reminder gets reassigned to the admin account first, then the throwaway
    account is deleted."""
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
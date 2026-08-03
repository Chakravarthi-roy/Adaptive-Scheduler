from sqlalchemy import create_engine, Column, String, DateTime, Boolean, Text, ForeignKey, Integer
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

engine     = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
Base       = declarative_base()


class User(Base):
    __tablename__ = "users"

    id            = Column(String, primary_key=True)
    email         = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    nickname      = Column(String, nullable=True)
    created_at    = Column(DateTime, nullable=True)
    is_demo       = Column(Boolean, default=False)
    is_admin      = Column(Boolean, default=False)
    vibration_enabled   = Column(Boolean, default=True)
    reset_token         = Column(String, nullable=True)
    reset_token_expires = Column(DateTime, nullable=True)

    # Synced settings (previously localStorage-only — see ISSUES.md #3).
    # Times stored as "HH:MM" strings, same convention as the <input type="time">
    # fields on the frontend; minutes stored as strings for consistency with
    # duration_minutes/pre_alert_minutes/etc. on Reminder. All nullable —
    # NULL means "never synced yet, frontend default applies".
    timezone             = Column(String, nullable=True)
    morning_time         = Column(String, nullable=True)
    evening_time         = Column(String, nullable=True)
    night_time           = Column(String, nullable=True)
    in_a_bit_minutes     = Column(String, nullable=True)
    after_a_while_minutes = Column(String, nullable=True)


class Session(Base):
    __tablename__ = "sessions"

    token      = Column(String, primary_key=True)
    user_id    = Column(String, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, nullable=True)


class Reminder(Base):
    __tablename__ = "reminders"

    id               = Column(String, primary_key=True)
    user_id          = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    title            = Column(String, nullable=False)
    datetime         = Column(DateTime, nullable=True)
    location         = Column(String, nullable=True)
    type             = Column(String, default="personal")
    repeat           = Column(String, default="none")
    participants     = Column(Text, default="[]")
    done             = Column(Boolean, default=False)
    notified         = Column(Boolean, default=False)
    pre_alerted      = Column(Boolean, default=False)
    follow_up_sent   = Column(Boolean, default=False)
    missed           = Column(Boolean, default=False)
    action_label     = Column(String, nullable=True)
    duration_minutes = Column(String, nullable=True)   # how long the task itself takes; NULL = unknown/legacy
    pre_alert_minutes = Column(String, nullable=True)
    follow_up_minutes = Column(String, nullable=True)
    is_demo_reminder = Column(Boolean, default=False)  # demo user's reminder, visible to admin only


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    id                = Column(String, primary_key=True)
    user_id           = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    subscription_json = Column(Text, nullable=False)


class PendingSignup(Base):
    """
    A signup that hasn't been verified yet. No `User` row exists until the
    OTP is confirmed (see /verify-signup in auth.py) — so there's no
    "unverified account" state to track on `User` at all, and nothing sits
    half-created if the code is never entered. Just expires and gets swept
    up by the cleanup cron.
    """
    __tablename__ = "pending_signups"

    email         = Column(String, primary_key=True)   # one pending signup per email; a retry overwrites it
    password_hash = Column(String, nullable=False)
    nickname      = Column(String, nullable=True)
    demo_token    = Column(String, nullable=True)       # carried through to the real signup once verified
    otp_code      = Column(String, nullable=False)
    otp_expires   = Column(DateTime, nullable=False)
    attempts      = Column(Integer, default=0)          # wrong-code attempts; capped to slow brute-forcing
    created_at    = Column(DateTime, nullable=True)


def init_db():
    Base.metadata.create_all(bind=engine)
from sqlalchemy import create_engine, Column, String, DateTime, Boolean, Text, ForeignKey
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
    reset_token         = Column(String, nullable=True)
    reset_token_expires = Column(DateTime, nullable=True)


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
    pre_alert_minutes = Column(String, nullable=True)
    follow_up_minutes = Column(String, nullable=True)
    is_demo_reminder = Column(Boolean, default=False)  # demo user's reminder, visible to admin only


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    id                = Column(String, primary_key=True)
    user_id           = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    subscription_json = Column(Text, nullable=False)


def init_db():
    Base.metadata.create_all(bind=engine)
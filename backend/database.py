from sqlalchemy import create_engine, Column, String, DateTime, Boolean, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

class Reminder(Base):
    __tablename__ = "reminders"

    id = Column(String, primary_key=True)
    title = Column(String, nullable=False)
    datetime = Column(DateTime, nullable=True)
    location = Column(String, nullable=True)
    type = Column(String, default="casual")
    repeat = Column(String, default="none")
    participants = Column(Text, default="[]")
    done = Column(Boolean, default=False)
    notified = Column(Boolean, default=False)
    pre_alerted = Column(Boolean, default=False)
    follow_up_sent = Column(Boolean, default=False)
    action_label = Column(String, nullable=True)  # e.g. 'Ate it 🍽️', 'Done ✓'

class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    id = Column(String, primary_key=True)
    subscription_json = Column(Text, nullable=False)

def init_db():
    Base.metadata.create_all(bind=engine)
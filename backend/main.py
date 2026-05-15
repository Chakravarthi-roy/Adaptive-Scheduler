from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from datetime import datetime
from database import SessionLocal, Reminder, PushSubscription, init_db
from pywebpush import webpush, WebPushException
import groq
import json
import uuid
import os
import tempfile
import pytz

load_dotenv()

IST = pytz.timezone('Asia/Kolkata')

client = groq.Groq(
    api_key=os.getenv("GROQ_API_KEY"),
    timeout=60.0
)
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY")
VAPID_EMAIL = os.getenv("VAPID_EMAIL")

FRONTEND_URL = os.getenv("FRONTEND_URL", "*")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL] if FRONTEND_URL != "*" else ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()

@app.get("/")
def root():
    return {"status": "backend running"}

@app.post("/transcribe")
async def transcribe(audio: UploadFile = File(...)):
    audio_bytes = await audio.read()

    # use tempfile instead of hardcoded path (safe for production)
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name

    with open(tmp_path, "rb") as f:
        transcript = client.audio.transcriptions.create(
            model="whisper-large-v3-turbo",
            file=f
        )

    os.remove(tmp_path)
    return {"transcript": transcript.text}

@app.post("/extract")
async def extract(data: dict):
    transcript = data.get("transcript", "")
    now = datetime.now(IST).strftime("%Y-%m-%d %H:%M")

    prompt = f"""
You are a reminder extraction assistant.
Current date and time: {now}

Extract reminder details from this voice input and return ONLY a JSON object.
No explanation, no markdown, no extra text. Just the JSON.

Voice input: "{transcript}"

Return this exact structure:
{{
  "title": "short clear title",
  "datetime": "YYYY-MM-DDTHH:MM:00 or null if unclear",
  "location": "location or null",
  "type": "meeting or medication or task or casual",
  "repeat": "none or daily or weekly",
  "participants": ["name"] or []
}}

Rules:
- "evening" means 18:00
- "morning" means 08:00
- "night" means 21:00
- "in a bit" means 10 minutes from now
- "next sunday" always means the sunday of next week
- strip filler words like ra, yaar, na, bro from the title
- if time is missing set datetime to null
- if no location set null
- keep title short and clean
"""

    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )

    raw = response.choices[0].message.content.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    extracted = json.loads(raw.strip())
    return extracted

@app.post("/reminders")
def save_reminder(data: dict):
    db = SessionLocal()
    try:
        reminder = Reminder(
            id=str(uuid.uuid4()),
            title=data.get("title", ""),
            datetime=datetime.fromisoformat(data["datetime"]) if data.get("datetime") else None,
            location=data.get("location"),
            type=data.get("type", "casual"),
            repeat=data.get("repeat", "none"),
            participants=json.dumps(data.get("participants", [])),
            done=False
        )
        db.add(reminder)
        db.commit()
        return {"status": "saved", "id": reminder.id}
    finally:
        db.close()

@app.get("/reminders")
def get_reminders():
    db = SessionLocal()
    try:
        reminders = db.query(Reminder).filter(Reminder.done == False).order_by(Reminder.datetime).all()
        return [
            {
                "id": r.id,
                "title": r.title,
                "datetime": r.datetime.isoformat() if r.datetime else None,
                "location": r.location,
                "type": r.type,
                "repeat": r.repeat,
                "participants": json.loads(r.participants),
                "done": r.done
            }
            for r in reminders
        ]
    finally:
        db.close()

@app.patch("/reminders/{reminder_id}/done")
def mark_done(reminder_id: str):
    db = SessionLocal()
    try:
        reminder = db.query(Reminder).filter(Reminder.id == reminder_id).first()
        if reminder:
            reminder.done = True
            db.commit()
            return {"status": "marked done"}
        return {"status": "not found"}
    finally:
        db.close()

@app.post("/subscribe")
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

@app.get("/send-test-notification")
@app.post("/send-test-notification")
def send_test():
    return send_notification(
        "Test Notification 🔔",
        "Your Adaptive Scheduler notifications are working!"
    )

def send_notification(title, body, persistent=False):
    db = SessionLocal()
    try:
        sub = db.query(PushSubscription).first()
        if not sub:
            return {"status": "no subscription found"}

        subscription = json.loads(sub.subscription_json)

        webpush(
            subscription_info=subscription,
            data=json.dumps({
                "title": title,
                "body": body,
                "persistent": persistent
            }),
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={"sub": VAPID_EMAIL}
        )
        return {"status": "sent"}
    except WebPushException as ex:
        print("push failed:", ex)
        return {"status": "failed", "error": str(ex)}
    finally:
        db.close()
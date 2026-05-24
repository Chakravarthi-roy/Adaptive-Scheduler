from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from datetime import datetime, timedelta
from database import SessionLocal, Reminder, PushSubscription, init_db
from pywebpush import webpush, WebPushException
from notification import build_notification, send_notification, PRE_ALERT_MINUTES
import groq
import json
import uuid
import os
import tempfile
import pytz

load_dotenv()

client = groq.Groq(
    api_key=os.getenv("GROQ_API_KEY"),
    timeout=60.0
)
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY")
VAPID_EMAIL = os.getenv("VAPID_EMAIL")
FRONTEND_URL = os.getenv("FRONTEND_URL", "*")

IST = pytz.timezone('Asia/Kolkata')

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL] if FRONTEND_URL != "*" else ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()

# ─── Agent Tools Definition ───────────────────────────────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_reminders",
            "description": "Get all existing reminders to understand the user's current schedule. Use this to resolve relative references like 'after my exam', 'before my meeting', and also to find reminders the user wants to delete.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": "Ask the user a clarifying question when information is missing or ambiguous. Use this when you need duration, exact time, or any detail you cannot infer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "A short, clear question to ask the user. Keep it conversational and friendly."
                    }
                },
                "required": ["question"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_reminder",
            "description": "Create a reminder once you have all the necessary information.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Short, clean title. Strip filler words like ra, yaar, na, bro, da."
                    },
                    "datetime": {
                        "type": "string",
                        "description": "ISO format datetime YYYY-MM-DDTHH:MM:00 or empty string if not applicable"
                    },
                    "location": {
                        "type": "string",
                        "description": "Location or empty string if none"
                    },
                    "type": {
                        "type": "string",
                        "enum": ["meeting", "medication", "task", "casual"],
                        "description": "Type of reminder"
                    },
                    "repeat": {
                        "type": "string",
                        "enum": ["none", "daily", "weekly"],
                        "description": "Repeat frequency"
                    },
                    "participants": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of participant names, always an empty array [] if none"
                    }
                },
                "required": ["title", "type", "repeat", "location", "participants"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_reminder",
            "description": "Delete one or more reminders by their IDs. Always call get_reminders first to find the correct reminder ID(s). If multiple reminders match, ask the user to clarify which one.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of reminder IDs to delete"
                    },
                    "confirmation": {
                        "type": "string",
                        "description": "A short human-readable message confirming what was deleted e.g. 'Deleted your 5pm meeting'"
                    }
                },
                "required": ["ids", "confirmation"]
            }
        }
    }
]

SYSTEM_PROMPT = """You are a smart reminder assistant that helps users create and manage reminders via voice or text.

IMPORTANT: You must use the available tools to help the user. Always respond with tool calls, not just text.

You have access to four tools:
1. get_reminders — see the user's existing schedule (call this first for any request)
2. ask_user — ask ONE clarifying question when information is missing
3. create_reminder — create a new reminder with all required fields
4. delete_reminder — delete reminders by ID

WORKFLOW:
1. First, always call get_reminders to see what reminders exist
2. If user wants to create: extract info, ask clarifying questions if needed, then call create_reminder
3. If user wants to delete: find the reminder ID first, then call delete_reminder
4. Be concise and conversational

Rules for CREATING reminders:
- Extract title, type, repeat, location, participants from user input
- type must be one of: "meeting", "medication", "task", "casual"
- repeat must be one of: "none", "daily", "weekly"
- location: empty string "" if not mentioned
- participants: always an array [], use empty array if none
- datetime: ISO format YYYY-MM-DDTHH:MM:00, or empty string "" if no specific time
- "evening" = 18:00, "morning" = 08:00, "night" = 21:00, "in a bit" = 10 mins from now
- "next sunday" = sunday of next week
- Strip filler words like ra, yaar, na, bro, da from titles

Rules for DELETING reminders:
- Call get_reminders first
- Find the reminder ID that matches user's description
- If ambiguous, use ask_user to clarify
- Always include what was deleted in confirmation"""


def get_reminders_tool():
    db = SessionLocal()
    try:
        reminders = db.query(Reminder).filter(Reminder.done == False).order_by(Reminder.datetime).all()
        return [
            {
                "id": r.id,
                "title": r.title,
                "datetime": r.datetime.isoformat() if r.datetime else None,
                "type": r.type,
                "repeat": r.repeat
            }
            for r in reminders
        ]
    finally:
        db.close()


def delete_reminders_tool(ids):
    db = SessionLocal()
    try:
        deleted = 0
        for reminder_id in ids:
            reminder = db.query(Reminder).filter(Reminder.id == reminder_id).first()
            if reminder:
                db.delete(reminder)
                deleted += 1
        db.commit()
        return {"deleted": deleted}
    finally:
        db.close()


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.api_route("/", methods=["GET", "HEAD"])
def root():
    return {"status": "backend running"}


@app.post("/transcribe")
async def transcribe(audio: UploadFile = File(...)):
    audio_bytes = await audio.read()
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


@app.post("/agent")
async def agent(data: dict):
    messages = data.get("messages", [])
    now = datetime.now(IST).strftime("%Y-%m-%d %H:%M")

    system = f"""{SYSTEM_PROMPT}

Current date and time (IST): {now}

RESPOND ONLY WITH JSON in this format:
{{"action": "get_reminders"}} - to see existing reminders
{{"action": "ask_user", "question": "Your question here"}} - to ask user for info
{{"action": "create_reminder", "title": "...", "datetime": "...", "location": "...", "type": "...", "repeat": "...", "participants": []}}
{{"action": "delete_reminder", "ids": [...], "confirmation": "..."}}

Always respond with ONLY valid JSON, no other text."""

    full_messages = [{"role": "user", "content": system}] + messages

    try:
        for _ in range(10):
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=full_messages,
                temperature=0
            )

            text = response.choices[0].message.content.strip()
            
            # Parse JSON response
            try:
                action_data = json.loads(text)
            except json.JSONDecodeError:
                print(f"Failed to parse JSON: {text}")
                return {"type": "error", "text": "Sorry, I had trouble understanding that. Please try again!"}

            action = action_data.get("action")

            if action == "get_reminders":
                result = get_reminders_tool()
                full_messages.append({"role": "assistant", "content": text})
                full_messages.append({"role": "user", "content": f"Here are existing reminders: {json.dumps(result)}"})

            elif action == "ask_user":
                return {
                    "type": "question",
                    "text": action_data.get("question", "Can you provide more details?"),
                    "messages": full_messages
                }

            elif action == "create_reminder":
                return {
                    "type": "reminder",
                    "data": action_data,
                    "messages": full_messages
                }

            elif action == "delete_reminder":
                delete_reminders_tool(action_data.get("ids", []))
                return {
                    "type": "deleted",
                    "text": action_data.get("confirmation", "Reminder deleted"),
                    "messages": full_messages
                }

    except Exception as e:
        print(f"Agent error: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        return {"type": "error", "text": "Sorry, I had trouble understanding that. Please try again!"}

    return {"type": "error", "text": "Something went wrong. Please try again."}

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


@app.post("/reminders/{reminder_id}/snooze")
def snooze_reminder(reminder_id: str):
    db = SessionLocal()
    try:
        reminder = db.query(Reminder).filter(Reminder.id == reminder_id).first()
        if reminder and reminder.datetime:
            from datetime import timedelta
            reminder.datetime = reminder.datetime + timedelta(minutes=10)
            reminder.notified = False
            reminder.pre_alerted = False
            db.commit()
            return {"status": "snoozed"}
        return {"status": "not found"}
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


# def send_notification(title, body, persistent=False, action=None, action_label=None, reminder_id=None):
#     db = SessionLocal()
#     try:
#         sub = db.query(PushSubscription).first()
#         if not sub:
#             return {"status": "no subscription found"}
#         subscription = json.loads(sub.subscription_json)

#         payload = {
#             "title": title,
#             "body": body,
#             "persistent": persistent,
#             "reminder_id": reminder_id
#         }

#         # add action button if provided
#         if action and action_label:
#             payload["action"] = action
#             payload["action_label"] = action_label

#         webpush(
#             subscription_info=subscription,
#             data=json.dumps(payload),
#             vapid_private_key=VAPID_PRIVATE_KEY,
#             vapid_claims={"sub": VAPID_EMAIL}
#         )
#         return {"status": "sent"}
#     except WebPushException as ex:
#         print("push failed:", ex)
#         return {"status": "failed", "error": str(ex)}
#     finally:
#         db.close()

@app.get("/cron/check-reminders")
def cron_check_reminders():
    """Endpoint for external cron service to trigger reminder checks"""
    db = SessionLocal()
    try:
        now = datetime.now(IST).replace(tzinfo=None)
        window_start = now - timedelta(seconds=30)
        window_end = now + timedelta(seconds=30)

        # Check pre-alerts
        for reminder_type, minutes in PRE_ALERT_MINUTES.items():
            if minutes == 0:
                continue
            pre_alert_window_start = window_start + timedelta(minutes=minutes)
            pre_alert_window_end = window_end + timedelta(minutes=minutes)

            due_pre = db.query(Reminder).filter(
                Reminder.done == False,
                Reminder.notified == False,
                Reminder.pre_alerted == False,
                Reminder.type == reminder_type,
                Reminder.datetime >= pre_alert_window_start,
                Reminder.datetime <= pre_alert_window_end
            ).all()

            for reminder in due_pre:
                notif = build_notification(reminder, is_pre_alert=True)
                if notif:
                    send_notification(
                        notif["title"],
                        notif["body"],
                        notif["persistent"],
                        action=notif["action"],
                        action_label=notif["action_label"],
                        reminder_id=reminder.id
                    )
                    reminder.pre_alerted = True

        # Check on-time notifications
        due = db.query(Reminder).filter(
            Reminder.done == False,
            Reminder.notified == False,
            Reminder.datetime >= window_start,
            Reminder.datetime <= window_end
        ).all()

        for reminder in due:
            notif = build_notification(reminder, is_pre_alert=False)
            send_notification(
                notif["title"],
                notif["body"],
                notif["persistent"],
                action=notif["action"],
                action_label=notif["action_label"],
                reminder_id=reminder.id
            )
            reminder.notified = True

            # Handle recurring
            if reminder.repeat == "daily":
                reminder.datetime = reminder.datetime + timedelta(days=1)
                reminder.notified = False
                reminder.pre_alerted = False
            elif reminder.repeat == "weekly":
                reminder.datetime = reminder.datetime + timedelta(weeks=1)
                reminder.notified = False
                reminder.pre_alerted = False

        db.commit()
        return {"status": "checked", "time": now.strftime("%H:%M:%S")}
    except Exception as e:
        print(f"Cron error: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        db.close()
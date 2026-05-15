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
            "description": "Get all existing reminders to understand the user's current schedule. Use this to resolve relative references like 'after my exam', 'before my meeting', etc.",
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
            "description": "Create a reminder once you have all the necessary information. Call this when you are confident about the reminder details.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Short, clean title for the reminder. Strip filler words."
                    },
                    "datetime": {
                        "type": "string",
                        "description": "ISO format datetime YYYY-MM-DDTHH:MM:00 or null if not applicable"
                    },
                    "location": {
                        "type": "string",
                        "description": "Location or null"
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
                        "description": "List of participant names if any"
                    }
                },
                "required": ["title", "type", "repeat"]
            }
        }
    }
]

SYSTEM_PROMPT = """You are a smart reminder assistant that helps users create reminders from voice or text input.

You have access to three tools:
1. get_reminders — to see the user's existing schedule
2. ask_user — to ask ONE clarifying question when needed
3. create_reminder — to create the reminder once you have all details

Rules:
- Always call get_reminders first to understand the user's existing schedule
- If the user says "after my exam/meeting/task", look at existing reminders to calculate the time
- If you need duration or any unclear detail, use ask_user to ask ONE focused question
- Strip filler words like ra, yaar, na, bro, da from titles
- "evening" = 18:00, "morning" = 08:00, "night" = 21:00, "in a bit" = 10 mins from now
- "next sunday" = sunday of next week
- Keep titles short and clean
- Be conversational and friendly in questions
- Once you have all info, call create_reminder immediately
- Never ask more than necessary — infer what you can"""


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
    """
    Main agent endpoint. Accepts conversation history and returns either:
    - { "type": "question", "text": "...", "messages": [...] }
    - { "type": "reminder", "data": {...}, "messages": [...] }
    """
    messages = data.get("messages", [])
    now = datetime.now(IST).strftime("%Y-%m-%d %H:%M")

    full_messages = [
        {"role": "system", "content": f"{SYSTEM_PROMPT}\n\nCurrent date and time (IST): {now}"}
    ] + messages

    for _ in range(10):
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=full_messages,
            tools=TOOLS,
            tool_choice="auto",
            temperature=0
        )

        message = response.choices[0].message

        if not message.tool_calls:
            return {"type": "question", "text": message.content, "messages": full_messages}

        full_messages.append({
            "role": "assistant",
            "content": message.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments
                    }
                }
                for tc in message.tool_calls
            ]
        })

        for tool_call in message.tool_calls:
            fn_name = tool_call.function.name
            fn_args = json.loads(tool_call.function.arguments)

            if fn_name == "get_reminders":
                result = get_reminders_tool()
                full_messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result)
                })

            elif fn_name == "ask_user":
                return {
                    "type": "question",
                    "text": fn_args["question"],
                    "messages": full_messages
                }

            elif fn_name == "create_reminder":
                return {
                    "type": "reminder",
                    "data": fn_args,
                    "messages": full_messages
                }

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
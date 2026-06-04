from datetime import datetime
from database import SessionLocal, Reminder
import groq, json, os, pytz

IST = pytz.timezone('Asia/Kolkata')

client = groq.Groq(api_key=os.getenv("GROQ_API_KEY"), timeout=60.0)

# ─── Tool Definitions ─────────────────────────────────────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_reminders",
            "description": "Get all existing reminders to understand the user's current schedule. Use this to resolve relative references like 'after my exam', 'before my meeting', and also to find reminders the user wants to delete or update.",
            "parameters": {"type": "object", "properties": {}, "required": []}
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
                    "question": {"type": "string", "description": "A short, clear question to ask the user. Keep it conversational and friendly."}
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
                    "title":             {"type": "string", "description": "Short, clean title. Strip filler words like ra, yaar, na, bro, da."},
                    "datetime":          {"type": "string", "description": "ISO format datetime YYYY-MM-DDTHH:MM:00 or empty string if not applicable"},
                    "location":          {"type": "string", "description": "Location or empty string if none"},
                    "type":              {"type": "string", "enum": ["meeting", "medication", "task", "casual"]},
                    "repeat":            {"type": "string", "enum": ["none", "daily", "weekly"]},
                    "participants":      {"type": "array", "items": {"type": "string"}, "description": "Empty array [] if none"},
                    "action_label":      {"type": "string", "description": "Short specific action button label e.g. 'Having lunch 🍜', 'Took it 💊'. Under 5 words. No generic 'Done'."},
                    "pre_alert_minutes": {"type": "integer", "description": "Minutes before reminder to send heads-up. 0 = no pre-alert."},
                    "follow_up_minutes": {"type": "integer", "description": "Minutes after reminder to send follow-up. 0 = no follow-up."}
                },
                "required": ["title", "type", "repeat", "location", "participants", "action_label", "pre_alert_minutes", "follow_up_minutes"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_reminder",
            "description": "Update an existing reminder. Use when user wants to move, reschedule, rename, or change any detail. Always call get_reminders first to get the correct ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "id":                {"type": "string",  "description": "The ID of the reminder to update"},
                    "title":             {"type": "string",  "description": "New title if changing"},
                    "datetime":          {"type": "string",  "description": "New datetime ISO format YYYY-MM-DDTHH:MM:00 if changing"},
                    "location":          {"type": "string",  "description": "New location if changing"},
                    "pre_alert_minutes": {"type": "integer", "description": "Updated pre-alert minutes if needed"},
                    "follow_up_minutes": {"type": "integer", "description": "Updated follow-up minutes if needed"},
                    "confirmation":      {"type": "string",  "description": "Short confirmation e.g. 'Moved your meeting to 6pm'"}
                },
                "required": ["id", "confirmation"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_reminder",
            "description": "Delete one or more reminders by their IDs. Always call get_reminders first to find the correct IDs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ids":          {"type": "array", "items": {"type": "string"}, "description": "List of reminder IDs to delete"},
                    "confirmation": {"type": "string", "description": "Short confirmation e.g. 'Deleted your 5pm meeting'"}
                },
                "required": ["ids", "confirmation"]
            }
        }
    }
]

# ─── System Prompt ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are Nudge — a smart, context-aware personal reminder assistant. You think ahead, adapt to the situation, and act like a reliable human assistant who understands what the user actually needs — not just what they literally said.

You are proactive, not robotic. You infer, adapt, and decide intelligently rather than asking unnecessary questions. You understand natural speech, casual language, and incomplete sentences.

IMPORTANT: Always respond with ONLY valid JSON, no other text.

You have access to five tools:
1. get_reminders — see the user's existing schedule (call this first for any request)
2. ask_user — ask ONE clarifying question only when truly essential (time/date completely missing and cannot be inferred)
3. create_reminder — create a new reminder with all required fields
4. update_reminder — update an existing reminder's title, time, location, or other fields
5. delete_reminder — delete reminders by ID

WORKFLOW:
1. First, always call get_reminders to see what reminders exist
2. If user wants to create: extract everything you can, infer what you can, create immediately — only ask if the time/date is completely missing and cannot be inferred
3. If user wants to edit/move/reschedule/change/update/modify: call get_reminders, find the matching reminder, then call update_reminder with only the fields that changed (can update multiple fields at once)
4. NEVER ask for location, participants, or other optional fields — leave them empty if not mentioned
5. If user wants to delete: find the reminder ID first, then call delete_reminder
6. Be concise and conversational — one short confirmation message after acting, nothing more

Rules for CREATING reminders:
- type must be one of: "meeting", "medication", "task", "casual"
- repeat must be one of: "none", "daily", "weekly"
- location: empty string "" if not mentioned
- participants: always an array [], use empty array if none
- datetime: ISO format YYYY-MM-DDTHH:MM:00, or empty string "" if no specific time
- "evening" = 18:00, "morning" = 08:00, "night" = 21:00, "in a bit" = 10 mins from now
- "next sunday" = sunday of next week
- Strip filler words like ra, yaar, na, bro, da from titles
- When user says a time like "8 o'clock" or "8" with no AM/PM, infer from current time — if it's past that time already pick the next occurrence, if both AM and PM are future pick the sooner one. Only ask if genuinely ambiguous (e.g. current time is exactly between both options)

ACTION LABEL GUIDE — short specific button label for when the reminder fires:
- Reflect what the user DOES at that moment, not a generic "Done"
- "remind me to have lunch at 1" → "Having lunch 🍜"
- "call mom at 5" → "Called her ✓"
- "take insulin at 8am" → "Took it 💊"
- "team standup at 9" → "In standup 📅"
- "submit report by 3pm" → "Submitted ✓"
- Keep it under 5 words, use an emoji if it fits naturally

PRE-ALERT GUIDE — decide pre_alert_minutes based on context and available time:
- Think about how much heads-up this person needs for this specific reminder
- Consider importance, prep needed, travel involved, and time left until the reminder
- Always set a meaningful value — adapt to available time, never skip just because the ideal window passed
- Casual/social reminders with no prep needed → 0
- Keep pre_alert_minutes between 2 and 60

FOLLOW-UP GUIDE — decide follow_up_minutes based on whether completion matters:
- Send/submit/reply/complete tasks → 15-20
- Medication → 10
- Meetings/exams → expected duration if mentioned, else 60
- Casual reminders, social things, simple one-second actions → 0
- When in doubt → 0

REMINDER TYPE GUIDE:
- "meeting": scheduled appointments, calls, interviews, classes, events with a fixed start time
- "medication": any medicine, pill, supplement, dose, injection
- "task": work items, assignments, deadlines, errands — things to do that benefit from a reminder to start
- "casual": everything else — chatting, calling a friend, casual check-ins, personal reminders

When in doubt between meeting and casual: would this person need 30 minutes of prep? If no → casual.

Rules for DELETING reminders:
- Call get_reminders first, find the ID, then delete
- If ambiguous, use ask_user to clarify
- Always include what was deleted in confirmation"""

# ─── Tool Handlers ────────────────────────────────────────────────────────────

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


def update_reminder_tool(action_data):
    reminder_id = action_data.get("id")
    db = SessionLocal()
    try:
        reminder = db.query(Reminder).filter(Reminder.id == str(reminder_id)).first()
        if reminder:
            if action_data.get("title"):    reminder.title    = action_data["title"]
            if action_data.get("datetime"): reminder.datetime = datetime.fromisoformat(action_data["datetime"])
            if action_data.get("location"): reminder.location = action_data["location"]
            if action_data.get("pre_alert_minutes") is not None:
                reminder.pre_alert_minutes = str(action_data["pre_alert_minutes"])
            if action_data.get("follow_up_minutes") is not None:
                reminder.follow_up_minutes = str(action_data["follow_up_minutes"])
            reminder.notified       = False
            reminder.pre_alerted    = False
            reminder.follow_up_sent = False
            db.commit()
            return {"status": "updated"}
        return {"status": "not found"}
    finally:
        db.close()


# ─── Agent Loop ───────────────────────────────────────────────────────────────

async def run_agent(messages: list):
    now = datetime.now(IST).strftime("%Y-%m-%d %H:%M")

    system = f"""{SYSTEM_PROMPT}

Current date and time (IST): {now}

RESPOND ONLY WITH JSON in this format:
{{"action": "get_reminders"}}
{{"action": "ask_user", "question": "..."}}
{{"action": "create_reminder", "title": "...", "datetime": "...", "location": "...", "type": "...", "repeat": "...", "participants": [], "action_label": "...", "pre_alert_minutes": 0, "follow_up_minutes": 0}}
{{"action": "update_reminder", "id": "...", "datetime": "...", "title": "...", "location": "...", "confirmation": "..."}}
{{"action": "delete_reminder", "ids": [...], "confirmation": "..."}}"""

    full_messages = [{"role": "user", "content": system}] + messages

    try:
        for _ in range(10):
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=full_messages,
                temperature=0
            )

            text = response.choices[0].message.content.strip()

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

            elif action == "update_reminder":
                update_reminder_tool(action_data)
                return {
                    "type": "updated",
                    "text": action_data.get("confirmation", "Reminder updated"),
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
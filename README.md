# Adaptive Scheduler

Hello everyone! 👋
This is my project **Adaptive Scheduler**.

## Tech Stack

- **Python**
- **FastAPI** for backend
- **HTML, CSS, JavaScript** for frontend
- **Supabase** for Database
- Hosted on **Render**. Link: *(add here)*

## Main Workflow

```
Voice → transcribe → keyword extraction used to create the reminder → create reminder → fire reminder → notification
```

So, basically the whole workflow goes down to:

> **Reminder creation, Reminder Firing**

## Features

1. [Missed reminders view](#1-missed-reminders-view)
2. [Done reminders view](#2-done-reminders-view)
3. [Settings](#3-settings)
4. [Pre-alerts based on the task or work](#4-pre-alerts)
5. [Follow-up reminders to confirm the completion of the work](#5-follow-up)
6. [Voice edit & delete](#6-voice-edit--delete)
7. [Typing box when you cannot speak](#7-typing-box-when-u-cannot-speak)
8. [Demo mode](#8-demo-mode)
9. [Converse with the agent about your past & upcoming schedule](#9-converse-with-the-agent-about-your-past--upcoming-schedule)

Let's break them one by one 👇

---

### 1. Missed reminders view

The reminders which are missed or not acknowledged by the user will be here. U can mark it as done until an hour after reminder firing and the application will give u a notification that u missed that reminder in that span of time.

### 2. Done reminders view

The reminders which u marked as done or gave acknowledgement to the notification will appear here.

### 3. Settings

We have interesting settings like:

- **Vague duration words** — there are some words which might mean different to different people and something the agent cannot comprehend. Phrases like *"in a bit"*, *"after a while"* etc mean a different value of time for different people so they can set the number according to their usability.
- **Vibration mode** *(still needs fixing)*
- **Reminder/notification tones** *(upcoming)*

### 4. Pre-alerts

This is an interesting one — something which i see no one seems to be providing.

For example, if we have an exam at 5PM in the evening, and if the application reminds u exactly on time, u might not have the time to prepare for it or u might be outside or in another work. So pre-alerts help u to prepare/set ur laptop, check the connection, and get pre-checks done on the test conducting platform, etc.

### 5. Follow-up

This could be a nice gesture after the task. This requires the **duration** of that task, which could be given by the user when creating the reminder, so that he can be gestured to follow-up on whether they have completed the task or not.

Again, something that most people like but none provide.

> The tricky part was duration itself — not every task has one. So i split it into 3 buckets:
> - **Instant stuff** (drink water) → `0`
> - **Fixed-duration stuff** (exam, movie) → agent asks once if u didn't mention it
> - **Self-paced stuff** (reading, studying) → agent asks how long *u* plan to spend, not how long the task "takes" (since that doesn't even make sense for something like reading a book)
> - **Open-ended decision stuff** (like picking a problem statement for a hackathon) → no duration at all, since there's no sensible number for that
>
> Agent asks only *once* and moves on with a default if u don't answer — it doesn't keep pestering u.

### 6. Voice edit & delete

I don't know why but i did not even add manual reminder deletion and updation. I just like to be able to edit or delete my reminders with my voice. And that is implemented — just say the title of the reminder and the agent checks which one it matches to, confirms with u if more than one exists (by asking a follow-up question), and then deletes or edits that particular reminder.

### 7. Typing box when u cannot speak

This is for the follow-up questions asked by the agent. U can either say it or u can type your reply in that chatbox, and it takes it as the response, skipping the transcribe step — which could reduce ur token usage.

### 8. Demo mode

A nice demo mode where u will get a walkthrough of the application — just the tour of the main & basic ones which appear to the users, to give them an idea of what they are.

### 9. Converse with the agent about your past & upcoming schedule

**This one i am most proud of.**

U can literally ask the agent things like *"do i have a gap today"* and it'll actually check your reminders between **7AM–6PM** and tell u exactly where u are free — not just guess.

Or ask something like *"did i attend the wedding last month"* and it'll search through your done/missed reminders and answer u — even if u don't phrase it exactly like the reminder title was.

---

*There is more to this... Upcoming*

---

## Now lets get technical!

### The Prompt

First most important thing in this project, since I am using **Groq APIs**, is the prompt. Let's see the flow of it.

Normally all the code used to just stay in one large file, `agent.py`. But I know that **architecture is very important** when building an Agent. So I turned that one file into components and connected them all one by one:

- `router.py` — figures out what the user actually wants (create/update/delete/query a reminder), just plain keyword matching, no LLM call needed for this part
- `context.py` — grabs the user's timezone before the agent even starts thinking
- `tools.py` — the actual functions that touch the database (get reminders, search, find free gaps, etc.)
- `prompts.py` — yep, prompts are a separate file now too
- `orchestrator.py` — ties everything above together, this is the actual loop

And the prompt part specifically — instead of one giant prompt trying to handle *everything* (creating, editing, deleting, answering questions), I split it into **4 separate prompts**, one per workflow, and only the relevant one gets loaded depending on what `router.py` decides. So the *create* prompt only knows about creating, the *query* prompt only knows about answering — nobody's carrying instructions they don't need. There's also a small shared block of rules (like *"always respond in valid JSON"*) that gets appended to all 4, so I'm not repeating myself four times over.

### The Prompt — full flow

Here's what's actually inside the **create** prompt specifically (the one that fires most, since making a new reminder is the main thing this app does). It's not just "extract the reminder" — it walks through a bunch of rules in order:

1. **Get the current reminders first** — before doing anything, the agent calls a tool to see what's already on the schedule. This matters for stuff like *"remind me after my exam"* — it needs to know when the exam actually is before it can figure out "after."
2. **Extract what it can, infer the rest** — title, date/time, location, all pulled straight from what I said.
3. **Time parsing rules** — things like *"evening" = 6PM*, *"in a bit" = 10 min from now*, *"next sunday" = the actual next Sunday*, etc. All spelled out explicitly so the model isn't guessing.
4. **Type classification** — every reminder gets sorted into one of 5 buckets: `important`, `health`, `routine`, `personal`, `casual`. This single field is what drives basically everything downstream — pre-alert defaults, follow-up defaults, how urgent the notification looks.
5. **Duration rules** — this was the trickiest part honestly (talked about this a bit in the Follow-up section above). Not every task even *has* a duration, so the prompt splits it into: instant stuff (0), externally-timed stuff like an exam or movie (agent asks *"how long is it?"*), self-paced stuff like reading or studying (agent asks *"how long do u want to spend?"* — different question, since a book doesn't have a fixed length), and open-ended decision stuff like picking a hackathon problem statement (no duration at all, doesn't even ask).
6. **Action label rules** — what button shows up on the notification. Not just a generic "Done ✓" for everything — it's supposed to be specific, like *"Took it 💊"* for medicine or *"Having lunch 🍜"* for food.
7. **Pre-alert rules** — defaults to 0 unless there's an actual reason to prep for something (travel, exam, medicine setup).
8. **Follow-up rules** — ties back into duration. If the agent knows/estimated how long something takes, the follow-up fires *duration + 10 min* later, so it's nudging u after the task is actually likely done, not at some random guessed time.
9. **The actual output** — at the very end, the prompt tells it exactly what JSON shape to respond in. No prose, no explanations, just one of a few fixed JSON actions (`get_reminders`, `ask_user`, `create_reminder`).

The other 3 prompts (`update`, `delete`, `query`) follow the same shape but way shorter, since they don't need all this — update/delete mostly just need to find the right reminder by ID and change/remove it, and query has its own separate set of rules around answering with real computed data instead of guessing.

### The Tools Layer

Every one of those JSON actions the LLM picks maps to an actual Python function — the model **never touches the database directly**, it only ever says *"I want to call this tool with these arguments"* and a separate piece of code does the real work. So there's a clean line: the LLM decides *what* to do, plain Python does *how*. Things like computing free gaps in a schedule, searching past reminders, updating/deleting rows — none of that logic lives inside a prompt, it's all regular code that can be tested and debugged on its own, separate from anything AI-related.

### Memory — how the conversation stays in sync

The backend doesn't actually hold onto the conversation between messages — every time I send something, the *entire* conversation history gets sent along with it, and the server rebuilds context from scratch each time. Sounds inefficient but it's actually the opposite — the server stays completely stateless, which means it can handle way more people at once without needing to remember who's talking to it or juggle sessions. All the "memory" that matters long-term (the actual reminders) just lives in the database and gets pulled in through tools whenever it's actually needed for that specific question.

### How the agent asks follow-up questions

The agent only asks when it actually needs to — and once it asks something, it **never asks the same thing twice** in one conversation. This works because the full conversation history (including the agent's own past questions) gets carried forward every turn, so next time around it can literally see "oh, I already asked about this" and just moves on with a reasonable default instead of repeating itself.

Same idea applies to duration specifically — if it's the kind of task that genuinely needs a duration (like an exam or a movie) and I didn't mention one, it'll ask *once*. If I don't answer clearly, it doesn't keep pestering me about it — it just picks a sensible default and moves on with creating the reminder.

### Ending the conversation properly

After the agent answers something (like *"do I have a gap today"*), the chat doesn't just sit there forever with no resolution. If I say *"thanks"*, it replies *"You're welcome! Anything else you'd like to know?"* — and if I follow that with a *"no"*, it says *"Okay, glad I could help!"* and closes the chat on its own. All of this is detected locally too, no need to even hit the backend just to notice someone said thanks.

But not everyone talks to an AI like that (fair enough), so there's also just a plain **"close chat" button** sitting right there the whole time — one tap, done, no need to say anything at all.

### Notifications & Cron Jobs

The application needs to check *every single minute* whether any reminder needs to fire — pre-alerts, the actual on-time notification, missed re-fires, and follow-ups. So I was thinking about how to do this and then I got to know about **cron jobs**!

I built one endpoint on the backend (`/cron/check-reminders`) that does all four of those checks whenever it's pinged. The only piece left was: *what pings it, every minute, forever, for free?*

There's quite a few options for this:
- **UptimeRobot**
- **cron-job.org**
- **Render's own Cron Jobs** feature

I ended up going with **cron-job.org**, and there's an actual reason for it, not just random pick — UptimeRobot's free tier only checks every **5 minutes**, which isn't fast enough for something that needs to fire *on time*. Render does have native Cron Jobs, but even the smallest one has a **$1/month minimum charge** — not exactly free. `cron-job.org`, on the other hand, lets you run jobs **every single minute, completely free**, no catch. So that's what's pinging my `/cron/check-reminders` endpoint right now.

### Push Notifications

Handles multiple devices per user (phone + laptop both get notified, not just one), and automatically drops subscriptions that have gone dead instead of letting them fail silently forever.

### Error handling — every step fails on its own

Each piece of the pipeline (the LLM call, parsing its JSON, calling a tool) catches its *own* errors now instead of one big catch-all wrapping the whole thing. So if, say, the database hiccups while updating a reminder, that shows up as a clean "couldn't save that, try again" instead of the whole request just dying with no explanation. Doesn't slow anything down either — a `try/except` that doesn't actually trigger costs basically nothing.

### Auth

Pretty standard stuff — email/password with `bcrypt` hashing, session tokens, and a forgot-password flow that emails a 30-min expiring reset link. Nothing fancy here.

What else?

---

## 🚀 Live

It is deployed on Render! URL: **https://adaptive-scheduler-frontend.onrender.com/**

Please check it out and suggest the issues by creating an issue if u would like.
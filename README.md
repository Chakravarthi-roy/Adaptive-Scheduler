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

## 🚀 Live

It is deployed on Render! URL: **https://adaptive-scheduler-frontend.onrender.com/**

Please check it out and suggest the issues by creating an issue if u would like.
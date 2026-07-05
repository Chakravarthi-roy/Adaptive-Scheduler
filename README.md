Hello everyone!
This is my project Adaptive scheduler

Tech stack:
Python
FastAPI for backend
HTML, CSS, JavaScript for frontend
Supabase for Database
Hosted on Render. Link: 

Main Workflow:
Voice -> transcribe -> keyword extraction used to create the reminder -> create reminder -> fire reminder -> notification

So, basically the whole workflow goes down to 
Reminder creation, Reminder Firing

Features:
1. missed reminders view
2. Done reminders view
3. Settings
4. Pre-alerts based on the task or work
5. Follow-up reminders to confirm the completion of the work
6. Voice edit & delete
7. Typing box when you cannot speak
8. Demo mode
9. Converse with the agent to about the past schdules (upcoming)

Let's break them one by one

1. missed reminders view:
    The reminders which are missed or not acknowledged by the user will be here. U can mark it as done until an hour after reminder firing and the application will give u notification that u missed that reminder in that span of time. 

2. Done reminders view:
    The reminders which u marked as done or gave acknowledgement to the notification will appear here. 

3. Settings
    We have interesting settings like, 
    there are some words which might mean different to different people and something the agent cannot comprehend. Phrases like, 'in a bit', 'after a while' etc mean a different value of time for different people so they can set the number according to their usability.
    Another one is the vibration mode (still needs fixing)
    Next one, upcoming (reminder/notification tones)

4. Pre-alerts
    This is an interesting one. something which i see no one seems to be providing. 
    For example, if we have an exam at 5PM in the evening, and if the application reminds u exactly on time, u might not have the time to prepare for it or u might be outside or in another work. So pre-alerts help u to prepare/set ur laptop, check the connection and pre checks done the test conducting platform etc. 

5. Follow-up
    This could be nice gesture after the task. this requires the duration of that task which could be given by the user when creating the reminder so that he cannot be gestured to see/follow-up if they have completed the task or not. 
    Again something that most people like but none provide.

6. Voice edit & delete
    I don't know why but i did not even add manual reminder deletion and updation. I just like to able to edit or delete my reminders with my voice. And that is implemented. Just say the title of the reminder and the agent checks which one it matches to and it confirms that reminder if there are more that exist (by asking a follow-up question) and then delete or edits that particular reminder.

7. Typing box when u cannot speak
    This is for the follow-up questions asked by the agent. U can either say it or u can type your reply in that chatbox and it takes it as the response skipping the transcribe! which could reduce ur token usage.

8. Demo mode
    A nice demo mode where u will get a walkthrough of the application, just the tour of the main & basic ones which appear to the users to give them an idea of what they are.


There is more to this... Upcoming


It is deployed on render! URL: https://adaptive-scheduler-frontend.onrender.com/
Please check it out and suggest the issues by creating an issue if would like. 
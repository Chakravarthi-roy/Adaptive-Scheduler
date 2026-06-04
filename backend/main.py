from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from database import init_db
from agent import run_agent
from reminders import router as reminders_router
from push import router as push_router
from scheduler import check_reminders
import groq, os, tempfile, pytz

load_dotenv()

IST = pytz.timezone('Asia/Kolkata')
client = groq.Groq(api_key=os.getenv("GROQ_API_KEY"), timeout=60.0)
FRONTEND_URL = os.getenv("FRONTEND_URL", "*")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL] if FRONTEND_URL != "*" else ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(reminders_router)
app.include_router(push_router)

init_db()


@app.api_route("/", methods=["GET", "HEAD"])
def root():
    return {"status": "Nudge backend running"}


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
    return await run_agent(messages)


@app.get("/cron/check-reminders")
def cron_check_reminders():
    return check_reminders()
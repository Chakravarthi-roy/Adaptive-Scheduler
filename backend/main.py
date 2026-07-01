from dotenv import load_dotenv
load_dotenv()   # must run before any local imports that read env vars at import time

from fastapi import FastAPI, UploadFile, File, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from rate_limit import limiter
from database import init_db
from agent import run_agent
from auth import router as auth_router, get_user_from_token
from reminders import router as reminders_router
from push import router as push_router
from scheduler import check_reminders
import groq, os, tempfile, pytz

IST = pytz.timezone('Asia/Kolkata')
client = groq.Groq(api_key=os.getenv("GROQ_API_KEY"), timeout=60.0)
FRONTEND_URL = os.getenv("FRONTEND_URL", "*")

# ─── Rate limiting ─────────────────────────────────────────────────────────────
# Keyed by IP address. Protects paid endpoints (Groq calls) and write endpoints
# from being hammered by one client, accidental loops, or a single bad actor.
app = FastAPI()
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL] if FRONTEND_URL != "*" else ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(reminders_router)
app.include_router(push_router)

init_db()


@app.api_route("/", methods=["GET", "HEAD"])
def root():
    return {"status": "Nudge backend running"}


@app.post("/transcribe")
@limiter.limit("20/minute")
async def transcribe(request: Request, audio: UploadFile = File(...)):
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
@limiter.limit("20/minute")
async def agent(request: Request, data: dict, authorization: str | None = Header(default=None)):
    user = get_user_from_token(authorization)
    if not user:
        raise HTTPException(status_code=401, detail="Please log in")
    messages = data.get("messages", [])
    return await run_agent(messages, user.id)


@app.get("/cron/check-reminders")
def cron_check_reminders():
    return check_reminders()
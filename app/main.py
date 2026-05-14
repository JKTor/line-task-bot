import os

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from linebot.v3 import WebhookParser
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from sqlalchemy.orm import Session

from app.database import get_db, init_db
from app.line_handler import handle_command
from app.scheduler import (
    check_and_send_reminders,
    check_routine_reminders,
    morning_digest,
    weekly_summary,
)

load_dotenv()

CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "")
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
CRON_SECRET = os.getenv("CRON_SECRET", "")

app = FastAPI(title="LINE Task Bot")

parser = WebhookParser(CHANNEL_SECRET) if CHANNEL_SECRET else None
line_config = Configuration(access_token=CHANNEL_ACCESS_TOKEN) if CHANNEL_ACCESS_TOKEN else None


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    print("[startup] DB ready")
    if not CHANNEL_SECRET or not CHANNEL_ACCESS_TOKEN:
        print("[startup] WARNING: LINE_CHANNEL_SECRET or LINE_CHANNEL_ACCESS_TOKEN is missing")


@app.get("/")
def root():
    return {"status": "ok", "service": "line-task-bot"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/debug/ai")
def debug_ai():
    return {
        "groq_set": bool(os.getenv("GROQ_API_KEY")),
        "gemini_set": bool(os.getenv("GEMINI_API_KEY")),
        "line_secret_set": bool(os.getenv("LINE_CHANNEL_SECRET")),
        "line_token_set": bool(os.getenv("LINE_CHANNEL_ACCESS_TOKEN")),
        "line_user_id_set": bool(os.getenv("LINE_USER_ID")),
    }


@app.post("/webhook")
async def webhook(request: Request, x_line_signature: str = Header(None), db: Session = Depends(get_db)):
    if parser is None or line_config is None:
        raise HTTPException(500, "LINE credentials not configured")

    body_bytes = await request.body()
    body = body_bytes.decode("utf-8")

    try:
        events = parser.parse(body, x_line_signature or "")
    except InvalidSignatureError:
        raise HTTPException(400, "Invalid signature")

    with ApiClient(line_config) as api_client:
        api = MessagingApi(api_client)
        for event in events:
            if not isinstance(event, MessageEvent):
                continue
            if not isinstance(event.message, TextMessageContent):
                continue
            user_id = event.source.user_id
            text = event.message.text or ""
            try:
                reply = handle_command(db, user_id, text)
            except Exception as e:
                print(f"[webhook] handler error: {e}")
                reply = "เกิดข้อผิดพลาด ลองใหม่อีกครั้งนะครับ"
            api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply)],
                )
            )
    return {"ok": True}


@app.get("/test/db")
def test_db(db: Session = Depends(get_db)):
    """Temporary test endpoint — verifies DB tables and columns exist."""
    from sqlalchemy import text
    from app.models import Routine
    results = {}

    try:
        r = Routine(user_id="__test__", title="test", time_hour=8, time_minute=0)
        db.add(r)
        db.commit()
        rid = r.id
        db.query(Routine).filter_by(id=rid).delete()
        db.commit()
        results["routines_table"] = "ok"
    except Exception as e:
        results["routines_table"] = str(e)

    try:
        rows = db.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='tasks' AND column_name='completed_at'"
        )).fetchall()
        results["completed_at_col"] = "ok" if rows else "missing"
    except Exception as e:
        results["completed_at_col"] = str(e)

    results["overall"] = "pass" if all(v == "ok" for v in results.values()) else "fail"
    return results


@app.get("/cron/check")
def cron_check(secret: str = ""):
    """External cron endpoint. Call every 1-5 minutes from cron-job.org.
    URL: https://your-app.onrender.com/cron/check?secret=YOUR_CRON_SECRET
    """
    if not CRON_SECRET or secret != CRON_SECRET:
        raise HTTPException(401, "Unauthorized")
    if not CHANNEL_ACCESS_TOKEN:
        raise HTTPException(500, "LINE access token not configured")
    sent = check_and_send_reminders(CHANNEL_ACCESS_TOKEN)
    sent += check_routine_reminders(CHANNEL_ACCESS_TOKEN)
    return {"ok": True, "reminders_sent": sent}


@app.get("/cron/morning")
def cron_morning(secret: str = ""):
    """Morning digest endpoint. Call daily at 01:00 UTC (08:00 Bangkok).
    URL: https://your-app.onrender.com/cron/morning?secret=YOUR_CRON_SECRET
    """
    if not CRON_SECRET or secret != CRON_SECRET:
        raise HTTPException(401, "Unauthorized")
    if not CHANNEL_ACCESS_TOKEN:
        raise HTTPException(500, "LINE access token not configured")
    sent = morning_digest(CHANNEL_ACCESS_TOKEN)
    return {"ok": True, "sent": sent}


@app.get("/cron/weekly")
def cron_weekly(secret: str = ""):
    """Weekly summary endpoint. Call every Sunday at 01:00 UTC (08:00 Bangkok).
    URL: https://your-app.onrender.com/cron/weekly?secret=YOUR_CRON_SECRET
    """
    if not CRON_SECRET or secret != CRON_SECRET:
        raise HTTPException(401, "Unauthorized")
    if not CHANNEL_ACCESS_TOKEN:
        raise HTTPException(500, "LINE access token not configured")
    sent = weekly_summary(CHANNEL_ACCESS_TOKEN)
    return {"ok": True, "sent": sent}

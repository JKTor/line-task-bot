import os
import pathlib
import threading

import requests
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
from typing import Optional

from dotenv import load_dotenv
from fastapi import Cookie, Depends, FastAPI, Form, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from linebot.v3 import WebhookParser
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    MessageAction,
    QuickReply,
    QuickReplyItem,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from sqlalchemy.orm import Session

from app.database import get_db, init_db
from app.line_handler import handle_command
from app.models import Task, UnknownMessage, User
from app.scheduler import (
    check_and_send_reminders,
    check_overdue_followup,
    check_routine_reminders,
    morning_digest,
    weekly_summary,
)

# Web UI dependencies — optional, won't crash LINE bot if missing
try:
    from fastapi.staticfiles import StaticFiles
    from fastapi.templating import Jinja2Templates
    from app.auth import (
        create_session_token, decode_session_token,
        exchange_code_for_profile, get_line_login_url,
        get_or_create_user, get_user_from_db, is_plan_active,
    )
    from app.middleware import check_can_add_task
    _TMPL_DIR = pathlib.Path("app/templates")
    templates = Jinja2Templates(directory=str(_TMPL_DIR)) if _TMPL_DIR.exists() else None
    WEB_ENABLED = templates is not None
    print(f"[startup] Web UI: {'enabled' if WEB_ENABLED else 'disabled (templates missing)'}")
except Exception as _e:
    print(f"[startup] Web UI disabled: {_e}")
    templates = None
    WEB_ENABLED = False


def _no_web():
    return JSONResponse({"error": "Web UI not available — check server logs"}, status_code=503)

load_dotenv()

CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "")
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
CRON_SECRET = os.getenv("CRON_SECRET", "")
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "")
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:8000")

app = FastAPI(title="LINE Task Bot")

parser = WebhookParser(CHANNEL_SECRET) if CHANNEL_SECRET else None
line_config = Configuration(access_token=CHANNEL_ACCESS_TOKEN) if CHANNEL_ACCESS_TOKEN else None

if WEB_ENABLED and pathlib.Path("app/static").exists():
    app.mount("/static", StaticFiles(directory="app/static"), name="static")

ONBOARDING_MSG = (
    f"สวัสดีครับ! 👋 ยินดีต้อนรับสู่ LINE Task Bot\n\n"
    f"พิมคำสั่งได้เลย เช่น:\n"
    f"• เพิ่ม ส่งรายงาน พรุ่งนี้ 18:00\n"
    f"• วันนี้มีอะไรบ้าง\n"
    f"• ช่วยเหลือ\n\n"
    f"🆓 Free plan: สร้างได้ 30 task\n"
    f"⚙️ ตั้งค่า Notion sync และดูงานบนเว็บ:\n{APP_BASE_URL}/dashboard"
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _get_session_user(session_token: Optional[str], db: Session) -> Optional[User]:
    if not WEB_ENABLED or not session_token:
        return None
    uid = decode_session_token(session_token)
    if not uid:
        return None
    return get_user_from_db(db, uid)


def _require_user(session_token: Optional[str] = Cookie(default=None),
                  db: Session = Depends(get_db)) -> User:
    user = _get_session_user(session_token, db)
    if not user:
        raise HTTPException(302, headers={"Location": "/auth/line"})
    return user


# ── startup ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
def on_startup() -> None:
    init_db()
    print("[startup] DB ready")
    if not CHANNEL_SECRET or not CHANNEL_ACCESS_TOKEN:
        print("[startup] WARNING: LINE credentials missing")

    # ── APScheduler ─────────────────────────────────────────────────────────
    import pytz
    tz = pytz.timezone("Asia/Bangkok")
    _scheduler = BackgroundScheduler(timezone=tz)

    # เช็ค deadline + routine reminders ทุก 5 นาที
    if CHANNEL_ACCESS_TOKEN:
        _scheduler.add_job(
            lambda: (check_and_send_reminders(CHANNEL_ACCESS_TOKEN),
                     check_routine_reminders(CHANNEL_ACCESS_TOKEN),
                     check_overdue_followup(CHANNEL_ACCESS_TOKEN)),
            'interval', minutes=5, id='reminder_check'
        )
        # morning digest ทุกวัน 08:00 Bangkok
        _scheduler.add_job(
            lambda: morning_digest(CHANNEL_ACCESS_TOKEN),
            'cron', hour=8, minute=0, id='morning_digest'
        )
        # weekly summary ทุกวันจันทร์ 09:00 Bangkok
        _scheduler.add_job(
            lambda: weekly_summary(CHANNEL_ACCESS_TOKEN),
            'cron', day_of_week='mon', hour=9, minute=0, id='weekly_summary'
        )

    # self-ping ทุก 10 นาที เพื่อไม่ให้ Render free tier หลับ
    def _keep_alive():
        try:
            url = APP_BASE_URL.rstrip('/') + '/health' if APP_BASE_URL else None
            if url:
                requests.get(url, timeout=10)
                print("[keep-alive] ping ok")
        except Exception as e:
            print(f"[keep-alive] error: {e}")

    _scheduler.add_job(_keep_alive, 'interval', minutes=10, id='keep_alive')
    _scheduler.start()
    print("[startup] APScheduler started — reminders every 5 min, morning digest at 08:00 BKK")


# ── public pages ──────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def landing(request: Request, error: str = "",
            session_token: Optional[str] = Cookie(default=None),
            db: Session = Depends(get_db)):
    user = _get_session_user(session_token, db)
    if user:
        return RedirectResponse("/dashboard")
    return templates.TemplateResponse("landing.html", {"request": request, "user": user, "error": error})


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/debug/ai")
def debug_ai():
    return {
        "groq_set": bool(os.getenv("GROQ_API_KEY")),
        "gemini_set": bool(os.getenv("GEMINI_API_KEY")),
        "line_secret_set": bool(CHANNEL_SECRET),
        "line_token_set": bool(CHANNEL_ACCESS_TOKEN),
        "line_login_set": bool(os.getenv("LINE_LOGIN_CLIENT_ID")),
    }


# ── auth ──────────────────────────────────────────────────────────────────────

@app.get("/auth/line")
def auth_line():
    url = get_line_login_url()
    return RedirectResponse(url)


@app.get("/auth/callback")
def auth_callback(code: str = "", state: str = "",
                   db: Session = Depends(get_db)):
    if not code:
        return RedirectResponse("/?error=ไม่ได้รับ+code+จาก+LINE")
    print(f"[auth] exchanging code for profile...")
    profile = exchange_code_for_profile(code)
    if not profile:
        return RedirectResponse("/?error=LINE+secret+ผิดหรือหมดอายุ+ตรวจสอบ+LINE_LOGIN_SECRET")

    user, is_new = get_or_create_user(
        db,
        line_user_id=profile.get("userId", ""),
        display_name=profile.get("displayName", ""),
        picture_url=profile.get("pictureUrl", ""),
    )
    token = create_session_token(user.line_user_id)
    response = RedirectResponse("/dashboard")
    response.set_cookie("session_token", token, max_age=86400 * 30, httponly=True, samesite="lax")
    return response


@app.get("/auth/logout")
def auth_logout():
    response = RedirectResponse("/")
    response.delete_cookie("session_token")
    return response


# ── dashboard ─────────────────────────────────────────────────────────────────

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request,
              session_token: Optional[str] = Cookie(default=None),
              db: Session = Depends(get_db),
              flash: str = ""):
    user = _get_session_user(session_token, db)
    if not user:
        return RedirectResponse("/auth/line")
    task_count = db.query(Task).filter_by(user_id=user.line_user_id, done=False).count()
    return templates.TemplateResponse("dashboard.html", {
        "request": request, "user": user,
        "task_count": task_count, "flash": flash,
    })


@app.post("/dashboard/settings")
def dashboard_settings(
    session_token: Optional[str] = Cookie(default=None),
    db: Session = Depends(get_db),
    notion_token: str = Form(default=""),
    notion_db_id: str = Form(default=""),
    quiet_start: str = Form(default=""),
    quiet_end: str = Form(default=""),
):
    user = _get_session_user(session_token, db)
    if not user:
        return RedirectResponse("/auth/line")
    if user.plan != "free":
        if notion_token:
            user.notion_token = notion_token.strip()
        if notion_db_id:
            user.notion_db_id = notion_db_id.strip()
    user.quiet_start = int(quiet_start) if quiet_start.isdigit() else None
    user.quiet_end = int(quiet_end) if quiet_end.isdigit() else None
    db.commit()
    return RedirectResponse("/dashboard?flash=บันทึกแล้ว", status_code=302)


@app.get("/dashboard/tasks", response_class=HTMLResponse)
def dashboard_tasks(request: Request,
                    filter: str = "all",
                    session_token: Optional[str] = Cookie(default=None),
                    db: Session = Depends(get_db)):
    user = _get_session_user(session_token, db)
    if not user:
        return RedirectResponse("/auth/line")
    import pytz
    from app.parser import now_local, TZ
    now = now_local()
    now_utc = now.astimezone(pytz.utc).replace(tzinfo=None)
    start_utc = now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(pytz.utc).replace(tzinfo=None)
    end_utc = start_utc + timedelta(days=1)
    tmr_end = start_utc + timedelta(days=2)

    q = db.query(Task).filter_by(user_id=user.line_user_id, done=False)
    if filter == "today":
        q = q.filter(Task.deadline >= start_utc, Task.deadline < end_utc)
    elif filter == "tomorrow":
        q = q.filter(Task.deadline >= end_utc, Task.deadline < tmr_end)
    elif filter == "overdue":
        q = q.filter(Task.deadline < now_utc)
    tasks_raw = q.order_by(Task.deadline.is_(None), Task.deadline.asc()).limit(100).all()

    tasks = []
    for t in tasks_raw:
        dl_local = None
        if t.deadline:
            dl_local = pytz.utc.localize(t.deadline).astimezone(TZ).strftime("%d/%m %H:%M")
        tasks.append({**t.__dict__, "deadline_local": dl_local})

    return templates.TemplateResponse("tasks.html", {
        "request": request, "user": user, "tasks": tasks, "filter": filter,
    })


# ── admin ─────────────────────────────────────────────────────────────────────

@app.get("/admin", response_class=HTMLResponse)
def admin_panel(request: Request, secret: str = "", db: Session = Depends(get_db)):
    if not ADMIN_SECRET or secret != ADMIN_SECRET:
        raise HTTPException(401, "Unauthorized")
    users_raw = db.query(User).order_by(User.created_at.desc()).all()
    users = []
    for u in users_raw:
        count = db.query(Task).filter_by(user_id=u.line_user_id, done=False).count()
        users.append({**u.__dict__, "task_count": count})
    return templates.TemplateResponse("admin.html", {
        "request": request, "users": users, "secret": secret,
    })


@app.post("/admin/activate")
def admin_activate(secret: str = Form(""), line_user_id: str = Form(""),
                   plan: str = Form("pro"), days: int = Form(30),
                   db: Session = Depends(get_db)):
    if not ADMIN_SECRET or secret != ADMIN_SECRET:
        raise HTTPException(401, "Unauthorized")
    user = db.query(User).filter_by(line_user_id=line_user_id).first()
    if not user:
        user = User(line_user_id=line_user_id, plan=plan)
        db.add(user)
    else:
        user.plan = plan
    user.plan_expires_at = (datetime.utcnow() + timedelta(days=days)) if days > 0 else None
    db.commit()
    return RedirectResponse(f"/admin?secret={secret}&flash=activated", status_code=302)


@app.get("/admin/unknown")
def admin_unknown(secret: str = "", resolved: bool = False, db: Session = Depends(get_db)):
    if not CRON_SECRET or secret != CRON_SECRET:
        raise HTTPException(401, "Unauthorized")
    msgs = (
        db.query(UnknownMessage)
        .filter(UnknownMessage.resolved == resolved)
        .order_by(UnknownMessage.created_at.desc())
        .limit(50)
        .all()
    )
    return [{"id": m.id, "text": m.text, "ai_intent": m.ai_intent,
             "created_at": m.created_at.isoformat() if m.created_at else None} for m in msgs]


@app.post("/admin/unknown/{msg_id}/resolve")
def admin_resolve(msg_id: int, secret: str = "", db: Session = Depends(get_db)):
    if not CRON_SECRET or secret != CRON_SECRET:
        raise HTTPException(401, "Unauthorized")
    msg = db.query(UnknownMessage).filter_by(id=msg_id).first()
    if not msg:
        raise HTTPException(404, "Not found")
    msg.resolved = True
    db.commit()
    return {"ok": True}


@app.delete("/admin/unknown/resolved")
def admin_clear_resolved(secret: str = "", db: Session = Depends(get_db)):
    if not CRON_SECRET or secret != CRON_SECRET:
        raise HTTPException(401, "Unauthorized")
    n = db.query(UnknownMessage).filter_by(resolved=True).delete()
    db.commit()
    return {"ok": True, "deleted": n}


# ── webhook ───────────────────────────────────────────────────────────────────

@app.post("/webhook")
async def webhook(request: Request, x_line_signature: str = Header(None),
                  db: Session = Depends(get_db)):
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

            # Auto-create user + onboarding (only when WEB_ENABLED)
            if WEB_ENABLED:
                user, is_new = get_or_create_user(db, user_id)
                if is_new:
                    reply = ONBOARDING_MSG
                    api.reply_message(ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=reply)]))
                    continue

                # Subscription gating for add commands
                if any(w in text for w in ("เพิ่ม", "add ")):
                    check = check_can_add_task(db, user_id)
                    if not check["ok"]:
                        api.reply_message(ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(text=check["message"])]))
                        continue

            try:
                reply = handle_command(db, user_id, text)
            except Exception as e:
                print(f"[webhook] handler error: {e}")
                reply = "เกิดข้อผิดพลาด ลองใหม่อีกครั้งนะครับ"

            if isinstance(reply, dict):
                qr_items = reply.get("quick_reply", [])
                qr = QuickReply(items=[
                    QuickReplyItem(action=MessageAction(label=item["label"], text=item["text"]))
                    for item in qr_items
                ]) if qr_items else None
                msg = TextMessage(text=reply["text"], quick_reply=qr)
            else:
                msg = TextMessage(text=reply)
            api.reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[msg]))
    return {"ok": True}


# ── cron ──────────────────────────────────────────────────────────────────────

@app.get("/cron/check")
def cron_check(secret: str = ""):
    if not CRON_SECRET or secret != CRON_SECRET:
        raise HTTPException(401, "Unauthorized")
    if not CHANNEL_ACCESS_TOKEN:
        raise HTTPException(500, "LINE access token not configured")
    sent = check_and_send_reminders(CHANNEL_ACCESS_TOKEN)
    sent += check_routine_reminders(CHANNEL_ACCESS_TOKEN)
    sent += check_overdue_followup(CHANNEL_ACCESS_TOKEN)
    return {"ok": True, "reminders_sent": sent}


@app.get("/cron/morning")
def cron_morning(secret: str = ""):
    if not CRON_SECRET or secret != CRON_SECRET:
        raise HTTPException(401, "Unauthorized")
    if not CHANNEL_ACCESS_TOKEN:
        raise HTTPException(500, "LINE access token not configured")
    sent = morning_digest(CHANNEL_ACCESS_TOKEN)
    return {"ok": True, "sent": sent}


@app.get("/cron/weekly")
def cron_weekly(secret: str = ""):
    if not CRON_SECRET or secret != CRON_SECRET:
        raise HTTPException(401, "Unauthorized")
    if not CHANNEL_ACCESS_TOKEN:
        raise HTTPException(500, "LINE access token not configured")
    sent = weekly_summary(CHANNEL_ACCESS_TOKEN)
    return {"ok": True, "sent": sent}

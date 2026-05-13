"""Reminder logic — find due tasks and push notifications via LINE."""
import os
from datetime import datetime, timedelta

import pytz
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    PushMessageRequest,
    TextMessage,
)

from app.database import SessionLocal
from app.models import Task
from app.parser import format_deadline, now_local

THAI_DAYS = ["จันทร์","อังคาร","พุธ","พฤหัสบดี","ศุกร์","เสาร์","อาทิตย์"]
THAI_MONTHS = ["","ม.ค.","ก.พ.","มี.ค.","เม.ย.","พ.ค.","มิ.ย.",
               "ก.ค.","ส.ค.","ก.ย.","ต.ค.","พ.ย.","ธ.ค."]
NUMBERED = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]


def _push(access_token: str, user_id: str, text: str) -> None:
    config = Configuration(access_token=access_token)
    with ApiClient(config) as api_client:
        api = MessagingApi(api_client)
        api.push_message(
            PushMessageRequest(to=user_id, messages=[TextMessage(text=text)])
        )


def check_and_send_reminders(access_token: str) -> int:
    """Send reminders for tasks whose deadline is within the next 60 minutes
    and that haven't been notified yet. Returns number of reminders sent."""
    db = SessionLocal()
    sent = 0
    try:
        now_utc = now_local().astimezone(pytz.utc).replace(tzinfo=None)
        soon_utc = (now_local() + timedelta(minutes=60)).astimezone(pytz.utc).replace(tzinfo=None)

        due_tasks = (
            db.query(Task)
            .filter(Task.done == False, Task.notified == False)  # noqa: E712
            .filter(Task.deadline.isnot(None))
            .filter(Task.deadline <= soon_utc)
            .all()
        )
        for task in due_tasks:
            overdue = task.deadline < now_utc
            prefix = "⏰ ใกล้ครบกำหนด!" if not overdue else "🚨 เลยกำหนดแล้ว!"
            text = (
                f"{prefix}\n"
                f"#{task.id} {task.title}\n"
                f"⏰ {format_deadline(task.deadline)}\n"
                f"พิมพ์ 'เสร็จ {task.id}' เมื่อทำเสร็จแล้ว"
            )
            try:
                _push(access_token, task.user_id, text)
                task.notified = True
                sent += 1
            except Exception as e:
                print(f"[reminder] failed for task {task.id}: {e}")
        db.commit()
        return sent
    finally:
        db.close()


def send_morning_summary(access_token: str) -> bool:
    """Push today's task summary. Returns True if message was sent."""
    user_id = os.getenv("LINE_USER_ID", "")
    if not user_id:
        print("[morning] LINE_USER_ID not set, skipping")
        return False

    db = SessionLocal()
    try:
        today_local = now_local()
        today_date = today_local.date()
        start_local = today_local.replace(hour=0, minute=0, second=0, microsecond=0)
        end_local = start_local + timedelta(days=1)
        start_utc = start_local.astimezone(pytz.utc).replace(tzinfo=None)
        end_utc = end_local.astimezone(pytz.utc).replace(tzinfo=None)

        tasks = (
            db.query(Task)
            .filter(Task.user_id == user_id, Task.done == False)  # noqa: E712
            .filter(Task.deadline >= start_utc, Task.deadline < end_utc)
            .order_by(Task.deadline.asc())
            .all()
        )

        day_name = THAI_DAYS[today_date.weekday()]
        date_str = f"วัน{day_name}ที่ {today_date.day} {THAI_MONTHS[today_date.month]} {today_date.year + 543}"

        if not tasks:
            text = (
                f"🌅 กุดมอร์นิ่ง! {date_str}\n\n"
                f"วันนี้ไม่มีงานค้างอยู่ 🎉\n"
                f"สนุกกับวันว่างได้เลยนะ!"
            )
        else:
            tz = today_local.tzinfo
            lines = [
                f"🌅 กุดมอร์นิ่ง! {date_str}\n",
                "〰〰〰〰〰〰〰〰〰〰",
                "📋 งานวันนี้ที่ต้องทำ",
                "〰〰〰〰〰〰〰〰〰〰",
            ]
            for i, t in enumerate(tasks):
                num = NUMBERED[i] if i < len(NUMBERED) else f"{i + 1}."
                t_local = pytz.utc.localize(t.deadline).astimezone(tz)
                lines.append(f"{num} {t.title} — {t_local.strftime('%H:%M')} น.")
            lines.append(f"\nมีงาน {len(tasks)} อย่างวันนี้ 🎯 สู้ๆ!")
            text = "\n".join(lines)

        _push(access_token, user_id, text)
        return True
    except Exception as e:
        print(f"[morning] failed: {e}")
        return False
    finally:
        db.close()

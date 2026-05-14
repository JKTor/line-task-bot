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
from app.models import Routine, Task
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


def check_routine_reminders(access_token: str) -> int:
    """Send routine reminders when it's within the advance window. Returns count sent."""
    db = SessionLocal()
    sent = 0
    try:
        now = now_local()
        today_str = now.date().isoformat()
        today_weekday = str(now.weekday())  # 0=Mon … 6=Sun

        routines = db.query(Routine).all()
        for routine in routines:
            try:
                # Day-of-week filter
                if routine.days != "daily":
                    allowed = [d.strip() for d in routine.days.split(",")]
                    if today_weekday not in allowed:
                        continue

                # Duplicate prevention
                if routine.last_notified_date == today_str:
                    continue

                # Clamp to valid time ranges (guard against bad AI data)
                h = max(0, min(23, routine.time_hour))
                m = max(0, min(59, routine.time_minute))

                # Build routine_dt for today; if already past, use tomorrow
                routine_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
                if routine_dt <= now:
                    routine_dt += timedelta(days=1)

                notify_dt = routine_dt - timedelta(minutes=routine.advance_minutes)
                delta = (now - notify_dt).total_seconds()

                if 0 <= delta < 300:  # within 5-minute cron window
                    text = (
                        f"⏰ อย่าลืม{routine.title}นะ!\n"
                        f"อีก {routine.advance_minutes} นาที "
                        f"({h:02d}:{m:02d})"
                    )
                    _push(access_token, routine.user_id, text)
                    routine.last_notified_date = today_str
                    sent += 1

            except Exception as e:
                print(f"[routine_reminder] failed for routine {routine.id}: {e}")

        db.commit()
        return sent
    finally:
        db.close()


def morning_digest(access_token: str) -> int:
    """Send 8 AM morning summary to all users with pending tasks or routines."""
    db = SessionLocal()
    sent = 0
    try:
        now = now_local()
        today_date = now.date()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        start_utc = today_start.astimezone(pytz.utc).replace(tzinfo=None)
        end_utc = today_end.astimezone(pytz.utc).replace(tzinfo=None)
        today_weekday = str(today_date.weekday())

        # Collect all users who have tasks or routines
        user_ids = {
            uid for (uid,) in
            db.query(Task.user_id).filter(Task.done == False).distinct().all()  # noqa: E712
        } | {
            uid for (uid,) in db.query(Routine.user_id).distinct().all()
        }

        for user_id in user_ids:
            today_tasks = (
                db.query(Task)
                .filter(Task.user_id == user_id, Task.done == False)  # noqa: E712
                .filter(Task.deadline.isnot(None))
                .filter(Task.deadline >= start_utc, Task.deadline < end_utc)
                .order_by(Task.deadline.asc())
                .all()
            )
            overdue_tasks = (
                db.query(Task)
                .filter(Task.user_id == user_id, Task.done == False)  # noqa: E712
                .filter(Task.deadline.isnot(None))
                .filter(Task.deadline < start_utc)
                .order_by(Task.deadline.asc())
                .all()
            )
            today_routines = (
                db.query(Routine)
                .filter(Routine.user_id == user_id)
                .filter(
                    (Routine.days == "daily") |
                    Routine.days.contains(today_weekday)
                )
                .order_by(Routine.time_hour, Routine.time_minute)
                .all()
            )

            if not today_tasks and not overdue_tasks and not today_routines:
                continue

            day_name = THAI_DAYS[today_date.weekday()]
            date_str = (
                f"วัน{day_name}ที่ {today_date.day} "
                f"{THAI_MONTHS[today_date.month]} {today_date.year + 543}"
            )
            tz = now.tzinfo
            lines = [f"🌅 กุดมอร์นิ่ง! {date_str}\n"]

            if today_tasks:
                lines.append("〰〰〰〰〰〰〰〰〰〰")
                lines.append(f"📋 งานวันนี้ ({len(today_tasks)} งาน)")
                lines.append("〰〰〰〰〰〰〰〰〰〰")
                for i, t in enumerate(today_tasks):
                    num = NUMBERED[i] if i < len(NUMBERED) else f"{i + 1}."
                    t_local = pytz.utc.localize(t.deadline).astimezone(tz)
                    recur_icon = " 🔄" if t.recurring else ""
                    lines.append(f"{num} {t.title}{recur_icon} — {t_local.strftime('%H:%M')} น.")

            if today_routines:
                lines.append("\n🔔 กิจวัตรวันนี้:")
                for r in today_routines:
                    lines.append(f"  • {r.title} — {r.time_hour:02d}:{r.time_minute:02d} น.")

            if overdue_tasks:
                lines.append("\n⚠️ งานที่เลยกำหนดแล้ว:")
                for t in overdue_tasks:
                    lines.append(f"  • #{t.id} {t.title}  ⏰ {format_deadline(t.deadline)}")

            lines.append("\n💪 สู้ๆ นะ!")
            try:
                _push(access_token, user_id, "\n".join(lines))
                sent += 1
            except Exception as e:
                print(f"[morning_digest] failed for {user_id}: {e}")

        return sent
    finally:
        db.close()


def weekly_summary(access_token: str) -> int:
    """Send weekly summary on Sundays. Returns number of users notified."""
    db = SessionLocal()
    sent = 0
    try:
        now = now_local()
        now_utc = now.astimezone(pytz.utc).replace(tzinfo=None)
        week_ago_utc = (now - timedelta(days=7)).astimezone(pytz.utc).replace(tzinfo=None)
        next_week_utc = (now + timedelta(days=7)).astimezone(pytz.utc).replace(tzinfo=None)

        user_ids = {uid for (uid,) in db.query(Task.user_id).distinct().all()} | {
            uid for (uid,) in db.query(Routine.user_id).distinct().all()
        }

        for user_id in user_ids:
            completed = (
                db.query(Task)
                .filter(Task.user_id == user_id, Task.done == True)  # noqa: E712
                .filter(Task.completed_at.isnot(None))
                .filter(Task.completed_at >= week_ago_utc, Task.completed_at <= now_utc)
                .all()
            )
            overdue = (
                db.query(Task)
                .filter(Task.user_id == user_id, Task.done == False)  # noqa: E712
                .filter(Task.deadline.isnot(None), Task.deadline < now_utc)
                .order_by(Task.deadline.asc())
                .all()
            )
            next_week = (
                db.query(Task)
                .filter(Task.user_id == user_id, Task.done == False)  # noqa: E712
                .filter(Task.deadline.isnot(None))
                .filter(Task.deadline >= now_utc, Task.deadline <= next_week_utc)
                .order_by(Task.deadline.asc())
                .all()
            )

            lines = [
                "📊 สรุปสัปดาห์นี้",
                "〰〰〰〰〰〰〰〰〰〰",
                f"✅ เสร็จแล้ว: {len(completed)} งาน",
                f"⚠️ เลยกำหนด: {len(overdue)} งาน",
                f"📅 สัปดาห์หน้า: {len(next_week)} งาน",
            ]
            if next_week:
                lines.append("\n📅 งานสัปดาห์หน้า:")
                tz = now.tzinfo
                for i, t in enumerate(next_week):
                    num = NUMBERED[i] if i < len(NUMBERED) else f"{i + 1}."
                    t_local = pytz.utc.localize(t.deadline).astimezone(tz)
                    lines.append(f"{num} {t.title} — {t_local.strftime('%d/%m %H:%M')} น.")
            if overdue:
                lines.append("\n⚠️ งานที่ค้างอยู่:")
                for t in overdue:
                    lines.append(f"  • #{t.id} {t.title}  ⏰ {format_deadline(t.deadline)}")

            try:
                _push(access_token, user_id, "\n".join(lines))
                sent += 1
            except Exception as e:
                print(f"[weekly_summary] failed for {user_id}: {e}")

        return sent
    finally:
        db.close()

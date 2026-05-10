"""Reminder logic — find due tasks and push notifications via LINE."""
from datetime import timedelta

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
            except Exception as e:  # log and continue with next task
                print(f"[reminder] failed for task {task.id}: {e}")
        db.commit()
        return sent
    finally:
        db.close()

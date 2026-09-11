"""งาน (Task) — เพิ่ม / ดูรายการ / ปิดงาน / เลื่อน / ลบ

`_list_agenda_for_date` รวมงานกับกิจวัตรของวันเดียวกันไว้ในข้อความเดียว จึงต้องเรียก
ฝั่ง routines ด้วย — ทิศทางการพึ่งพาเป็นทางเดียว (tasks → routines) ไม่วนกลับ
"""
from datetime import datetime, timedelta
from typing import List, Optional

import pytz
from sqlalchemy.orm import Session

from app.handlers.constants import _PRIORITY_EMOJI, _PRIORITY_VALID, NUMBERED
from app.handlers.formatting import (
    _ai_deadline_to_utc,
    _format_routine_line,
    _format_task_line,
    _label_for_date,
    _list_message,
    _next_recurring_deadline,
    _recurring_label,
    _task_quick_reply,
)
from app.handlers.routines import _get_routines_for_date, _routine_matches_date
from app.models import Routine, Task, User
from app.parser import TZ, now_local

def _get_tasks_for_date(db: Session, user_id: str, target_date) -> List[Task]:
    start_local = TZ.localize(datetime(target_date.year, target_date.month, target_date.day))
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(pytz.utc).replace(tzinfo=None)
    end_utc = end_local.astimezone(pytz.utc).replace(tzinfo=None)
    return (
        db.query(Task)
        .filter(Task.user_id == user_id, Task.done == False)  # noqa: E712
        .filter(Task.deadline >= start_utc, Task.deadline < end_utc)
        .order_by(Task.deadline.asc())
        .all()
    )

def _list_agenda_for_date(db: Session, user_id: str, target_date, header: str) -> str:
    tasks = _get_tasks_for_date(db, user_id, target_date)
    routines = _get_routines_for_date(db, user_id, target_date)
    if not tasks and not routines:
        return f"{header}\n(ไม่มีงานหรือกิจวัตร 🎉)"

    lines = [header]
    if tasks:
        lines.append("\n📋 งาน:")
        lines.extend(_format_task_line(t) for t in tasks)
    if routines:
        lines.append("\n🔔 กิจวัตร:")
        lines.extend(_format_routine_line(r) for r in routines)
    return "\n".join(lines)

def _format_add_beautiful(db: Session, user_id: str, new_task: Task) -> dict:
    recur_str = f"\n{_recurring_label(new_task.recurring)}" if new_task.recurring else ""
    if not new_task.deadline:
        text = f"✅ เพิ่มงานแล้ว!\n📋 #{new_task.id} {new_task.title}{recur_str}\n(ไม่มีกำหนดส่ง)"
        return {"text": text, "quick_reply": _task_quick_reply(new_task.id)}
    local_dt = pytz.utc.localize(new_task.deadline).astimezone(TZ)
    target_date = local_dt.date()
    label = _label_for_date(target_date)
    time_str = local_dt.strftime("%H:%M")
    added_block = (
        f"〰〰〰〰〰〰〰〰〰〰\n"
        f"📌 งานที่เพิ่ม:\n"
        f"📋 {new_task.title}\n"
        f"📅 {label} | 🕒 {time_str} น.{recur_str}\n"
        f"〰〰〰〰〰〰〰〰〰〰"
    )
    same_day = _get_tasks_for_date(db, user_id, target_date)
    if len(same_day) <= 1:
        summary = ""
    else:
        lines = [f"\n📊 สรุปงาน{label}ทั้งหมด ({len(same_day)} งาน):"]
        for i, t in enumerate(same_day):
            num = NUMBERED[i] if i < len(NUMBERED) else f"{i + 1}."
            t_local = pytz.utc.localize(t.deadline).astimezone(TZ)
            recur_icon = " 🔄" if t.recurring else ""
            lines.append(f"{num} {t.title}{recur_icon} — {t_local.strftime('%H:%M')} น.")
        summary = "\n".join(lines)
    text = f"✅ เพิ่มงานแล้ว!\n\n{added_block}{summary}\n\n💪 สู้ๆ นะ!"
    return {"text": text, "quick_reply": _task_quick_reply(new_task.id)}

def _add_task(db: Session, user_id: str, title: str, deadline: Optional[datetime],
              recurring: Optional[str] = None, priority: str = "normal",
              note: Optional[str] = None) -> Task:
    p = priority if priority in _PRIORITY_VALID else "normal"
    task = Task(user_id=user_id, title=title, deadline=deadline, recurring=recurring,
                priority=p, note=note)
    db.add(task)
    db.commit()
    db.refresh(task)
    try:
        from app import notion_sync
        user = db.query(User).filter_by(line_user_id=user_id).first()
        if user and user.notion_token and user.notion_db_id:
            notion_sync.sync_task(user.notion_token, user.notion_db_id, title, deadline)
    except Exception as e:
        print(f"[notion] sync error: {e}")
    return task


def _list_today(db: Session, user_id: str) -> str:
    today_local = now_local().date()
    return _list_agenda_for_date(db, user_id, today_local, f"📅 วันนี้ ({today_local.strftime('%d/%m')})")


def _list_tomorrow(db: Session, user_id: str) -> str:
    tomorrow_local = (now_local() + timedelta(days=1)).date()
    return _list_agenda_for_date(db, user_id, tomorrow_local, f"📅 พรุ่งนี้ ({tomorrow_local.strftime('%d/%m')})")


def _list_this_week(db: Session, user_id: str) -> str:
    now = now_local()
    start_local = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=7)
    start_utc = start_local.astimezone(pytz.utc).replace(tzinfo=None)
    end_utc = end_local.astimezone(pytz.utc).replace(tzinfo=None)
    tasks = (
        db.query(Task)
        .filter(Task.user_id == user_id, Task.done == False)  # noqa: E712
        .filter(Task.deadline.isnot(None))
        .filter(Task.deadline >= start_utc, Task.deadline < end_utc)
        .order_by(Task.deadline.asc())
        .all()
    )
    routines = (
        db.query(Routine)
        .filter_by(user_id=user_id)
        .order_by(Routine.time_hour, Routine.time_minute)
        .all()
    )
    week_dates = [(start_local + timedelta(days=i)).date() for i in range(7)]
    routine_lines = []
    for target_date in week_dates:
        matched = [r for r in routines if _routine_matches_date(r, target_date)]
        if matched:
            label = _label_for_date(target_date)
            for r in matched:
                routine_lines.append(f"🔔 {label} #{r.id} {r.title}  ⏰ {r.time_hour:02d}:{r.time_minute:02d}")

    if not tasks and not routine_lines:
        return "📅 7 วันข้างหน้า\n(ไม่มีงานหรือกิจวัตร 🎉)"
    lines = ["📅 7 วันข้างหน้า"]
    if tasks:
        lines.append("\n📋 งาน:")
        lines.extend(_format_task_line(t) for t in tasks)
    if routine_lines:
        lines.append("\n🔔 กิจวัตร:")
        lines.extend(routine_lines[:20])
        if len(routine_lines) > 20:
            lines.append(f"...และอีก {len(routine_lines) - 20} รายการ")
    return "\n".join(lines)


def _list_overdue(db: Session, user_id: str) -> str:
    now_utc = now_local().astimezone(pytz.utc).replace(tzinfo=None)
    tasks = (
        db.query(Task)
        .filter(Task.user_id == user_id, Task.done == False)  # noqa: E712
        .filter(Task.deadline.isnot(None))
        .filter(Task.deadline < now_utc)
        .order_by(Task.deadline.asc())
        .all()
    )
    return _list_message(tasks, "🚨 งานที่เลยกำหนดแล้ว")


def _list_date(db: Session, user_id: str, date_str: str) -> str:
    try:
        target = datetime.strptime(date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return "ไม่เข้าใจวันที่ที่ระบุ ลองพิมพ์ใหม่นะครับ"
    label = _label_for_date(target)
    return _list_agenda_for_date(db, user_id, target, f"📅 {label} ({target.strftime('%d/%m')})")


def _list_all(db: Session, user_id: str) -> str:
    tasks = (
        db.query(Task)
        .filter(Task.user_id == user_id, Task.done == False)  # noqa: E712
        .order_by(Task.deadline.is_(None), Task.deadline.asc())
        .all()
    )
    return _list_message(tasks, "📋 งานที่ยังไม่เสร็จ")


def _list_urgent(db: Session, user_id: str) -> str:
    tasks = (
        db.query(Task)
        .filter(Task.user_id == user_id, Task.done == False)  # noqa: E712
        .filter(Task.priority.in_(["urgent", "high"]))
        .order_by(Task.priority.asc(), Task.deadline.is_(None), Task.deadline.asc())
        .all()
    )
    return _list_message(tasks, "🔴 งานด่วน / สำคัญ")


def _search_tasks(db: Session, user_id: str, keyword: str) -> str:
    if not keyword:
        return "ระบุ keyword ด้วยนะครับ เช่น 'หางาน KBank'"
    kw = f"%{keyword}%"
    tasks = (
        db.query(Task)
        .filter(Task.user_id == user_id, Task.done == False)  # noqa: E712
        .filter(Task.title.ilike(kw) | Task.note.ilike(kw))
        .order_by(Task.deadline.is_(None), Task.deadline.asc())
        .all()
    )
    return _list_message(tasks, f"🔍 ผลการค้นหา: {keyword}")


def _add_note(db: Session, user_id: str, task_id: int, note_text: str) -> str:
    task = db.query(Task).filter_by(id=task_id, user_id=user_id).first()
    if not task:
        return f"ไม่เจองาน #{task_id}"
    task.note = note_text[:500]
    db.commit()
    return f"📝 เพิ่มโน้ตแล้ว: #{task_id} {task.title}\n{task.note}"


def _set_priority(db: Session, user_id: str, task_id: int, priority: str) -> str:
    task = db.query(Task).filter_by(id=task_id, user_id=user_id).first()
    if not task:
        return f"ไม่เจองาน #{task_id}"
    p = priority if priority in _PRIORITY_VALID else "normal"
    task.priority = p
    db.commit()
    emoji = _PRIORITY_EMOJI.get(p, "⬜")
    return f"{emoji} ตั้ง priority แล้ว: #{task_id} {task.title} → {p}"


def _mark_done(db: Session, user_id: str, task_id: int) -> str:
    task = db.query(Task).filter_by(id=task_id, user_id=user_id).first()
    if not task:
        return f"ไม่เจองาน #{task_id}"
    if task.done:
        return f"งาน #{task_id} เสร็จแล้วนะครับ ✅"
    task.done = True
    task.completed_at = datetime.utcnow()
    db.commit()
    msg = f"🎉 ทำเครื่องหมายเสร็จแล้ว: #{task.id} {task.title}"
    if task.recurring and task.deadline:
        next_dl = _next_recurring_deadline(task.recurring, task.deadline)
        if next_dl:
            new_task = _add_task(db, user_id, task.title, next_dl, task.recurring)
            local_dt = pytz.utc.localize(next_dl).astimezone(TZ)
            label = _label_for_date(local_dt.date())
            msg += f"\n🔄 สร้างรอบถัดไปแล้ว: {label} {local_dt.strftime('%H:%M')} น."
    return msg


def _delete_task(db: Session, user_id: str, task_id: int) -> str:
    task = db.query(Task).filter_by(id=task_id, user_id=user_id).first()
    if not task:
        return f"ไม่เจองาน #{task_id}"
    title = task.title
    db.delete(task)
    db.commit()
    return f"🗑️ ลบงานแล้ว: #{task_id} {title}"


def _delete_all(db: Session, user_id: str) -> str:
    n = db.query(Task).filter_by(user_id=user_id).delete()
    db.commit()
    return f"🗑️ ลบงานทั้งหมดแล้ว ({n} รายการ)" if n else "ไม่มีงานให้ลบ"


def _done_all(db: Session, user_id: str) -> str:
    n = (
        db.query(Task)
        .filter(Task.user_id == user_id, Task.done == False)  # noqa: E712
        .update({Task.done: True, Task.completed_at: datetime.utcnow()})
    )
    db.commit()
    return f"🎉 ปิดงานทั้งหมดแล้ว ({n} รายการ)" if n else "ไม่มีงานที่ค้างอยู่"


def _cancel_recurring(db: Session, user_id: str, task_id: int) -> str:
    task = db.query(Task).filter_by(id=task_id, user_id=user_id).first()
    if not task:
        return f"ไม่เจองาน #{task_id}"
    if not task.recurring:
        return f"งาน #{task_id} ไม่ได้ตั้งค่าซ้ำไว้"
    task.recurring = None
    db.commit()
    return f"🔄❌ ยกเลิกการทำซ้ำแล้ว: #{task.id} {task.title}"


def _snooze_task(db: Session, user_id: str, task_id: int, new_deadline_str: Optional[str]) -> str:
    task = db.query(Task).filter_by(id=task_id, user_id=user_id).first()
    if not task:
        return f"ไม่เจองาน #{task_id}"
    new_dl = _ai_deadline_to_utc(new_deadline_str)
    if not new_dl:
        return "ระบุวันที่ใหม่ด้วยนะครับ เช่น 'เลื่อนงาน 3 เป็นพรุ่งนี้ 18:00'"
    task.deadline = new_dl
    task.notified = False
    db.commit()
    local_dt = pytz.utc.localize(new_dl).astimezone(TZ)
    label = _label_for_date(local_dt.date())
    return f"📅 เลื่อนงาน #{task_id} แล้ว\n{task.title}\n⏰ {label} {local_dt.strftime('%H:%M')} น."

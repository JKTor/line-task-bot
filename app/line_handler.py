"""Handle text commands from LINE users.

Strategy: try strict pattern matching first (fast, free, predictable).
If nothing matches and AI is configured, fall back to AI parsing.
"""
import calendar
from datetime import datetime, timedelta
from typing import List, Optional

import pytz
from sqlalchemy.orm import Session

from app import ai_parser, expense
from app.models import PendingClarify, Routine, Task, UnknownMessage, User
from app.parser import TZ, format_deadline, now_local, parse_task

# How long a "waiting for the user to supply a date" state stays valid.
_PENDING_TTL_MIN = 10
# Match cancel only against the *whole* short reply — never as a substring.
# ("เลิก" as a substring would wrongly cancel answers like "หลังเลิกงาน 6 โมง".)
_CANCEL_WORDS = {"ยกเลิก", "ไม่ต้อง", "ไม่ต้องแล้ว", "ไม่เอา", "ไม่เอาแล้ว", "เลิก", "cancel"}


def _is_cancel(text: str) -> bool:
    t = text.strip().lower()
    return t in _CANCEL_WORDS or t.startswith("ยกเลิก")

HELP_TEXT = (
    "📝 คำสั่งที่ใช้ได้:\n"
    "• เพิ่ม <งาน> [วันเวลา] — เช่น เพิ่ม ส่งรายงาน พรุ่งนี้ 18:00\n"
    "• วันนี้ — ดูงานวันนี้\n"
    "• พรุ่งนี้ — ดูงานพรุ่งนี้\n"
    "• อาทิตย์นี้ — ดูงาน 7 วันข้างหน้า\n"
    "• ทั้งหมด — ดูงานที่ยังไม่เสร็จทั้งหมด\n"
    "• เสร็จ <id> — ทำเครื่องหมายเสร็จ\n"
    "• ลบ <id> — ลบงาน\n"
    "• ยกเลิกซ้ำ <id> — หยุดการทำซ้ำ\n"
    "• กิจวัตร — ดูกิจวัตรประจำวัน\n"
    "• ลบกิจวัตร <id> — ลบกิจวัตร\n"
    "• ลบกิจวัตรทั้งหมด — ลบกิจวัตรทั้งหมด\n"
    "• ช่วยเหลือ — แสดงคำสั่งทั้งหมด\n\n"
    "💸 รายรับ-รายจ่าย:\n"
    "• <ของ> <ราคา> — เช่น 'กาแฟ 60' บันทึกรายจ่ายทันที\n"
    "• รับ <ที่มา> <จำนวน> — เช่น 'รับ เงินเดือน 15000'\n"
    "• สรุป — สรุปรายจ่ายเดือนนี้แยกหมวด\n"
    "• รายจ่ายวันนี้ / เมื่อวาน — ดูรายการรายวัน\n"
    "• ลบรายจ่าย <id> — ลบรายการเงิน\n\n"
    "💡 พิมพ์ธรรมชาติก็ได้ เช่น 'พรุ่งนี้ส่งรายงาน 6 โมงเย็น'\n"
    "🔄 งานซ้ำ: 'ส่งรายงานทุกวันศุกร์ 5 โมงเย็น'\n"
    "🔔 กิจวัตร: 'ออกกำลังกายทุกวัน 18.00' (แจ้งเตือน ไม่ต้อง mark done)"
)

THAI_MONTHS = ["","ม.ค.","ก.พ.","มี.ค.","เม.ย.","พ.ค.","มิ.ย.",
               "ก.ค.","ส.ค.","ก.ย.","ต.ค.","พ.ย.","ธ.ค."]

THAI_WEEKDAYS = ["จันทร์","อังคาร","พุธ","พฤหัสบดี","ศุกร์","เสาร์","อาทิตย์"]

NUMBERED = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]

_ROUTINE_DAY_NAMES = {
    "0": "จันทร์", "1": "อังคาร", "2": "พุธ",
    "3": "พฤหัส", "4": "ศุกร์", "5": "เสาร์", "6": "อาทิตย์",
}


# ===== Helpers =====

_PRIORITY_EMOJI = {"urgent": "🔴", "high": "🟠", "normal": "⬜", "low": "🔵"}
_PRIORITY_VALID = {"urgent", "high", "normal", "low"}


def _format_task_line(t: Task) -> str:
    mark = "✅" if t.done else _PRIORITY_EMOJI.get(getattr(t, "priority", "normal") or "normal", "⬜")
    recur = " 🔄" if t.recurring else ""
    note_mark = " 📝" if getattr(t, "note", None) else ""
    return f"{mark} #{t.id} {t.title}{recur}{note_mark}  ⏰ {format_deadline(t.deadline)}"


def _list_message(tasks: List[Task], header: str) -> str:
    if not tasks:
        return f"{header}\n(ไม่มีงาน 🎉)"
    return "\n".join([header] + [_format_task_line(t) for t in tasks])


def _routine_matches_date(routine: Routine, target_date) -> bool:
    if routine.days == "daily":
        return True
    weekday = str(target_date.weekday())
    return weekday in [d.strip() for d in routine.days.split(",")]


def _get_routines_for_date(db: Session, user_id: str, target_date) -> List[Routine]:
    routines = (
        db.query(Routine)
        .filter_by(user_id=user_id)
        .order_by(Routine.time_hour, Routine.time_minute)
        .all()
    )
    return [r for r in routines if _routine_matches_date(r, target_date)]


def _format_routine_line(routine: Routine) -> str:
    return f"🔔 #{routine.id} {routine.title}  ⏰ {routine.time_hour:02d}:{routine.time_minute:02d}"


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


def _ai_deadline_to_utc(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            local = TZ.localize(datetime.strptime(s, fmt))
            return local.astimezone(pytz.utc).replace(tzinfo=None)
        except ValueError:
            continue
    return None


def _label_for_date(target_date) -> str:
    today = now_local().date()
    if target_date == today:
        return "วันนี้"
    if target_date == today + timedelta(days=1):
        return "พรุ่งนี้"
    return f"{target_date.day} {THAI_MONTHS[target_date.month]}"


def _recurring_label(recurring: str) -> str:
    if recurring == "daily":
        return "🔄 ซ้ำทุกวัน"
    if recurring.startswith("weekly:"):
        try:
            day = THAI_WEEKDAYS[int(recurring.split(":")[1])]
            return f"🔄 ซ้ำทุกวัน{day}"
        except (ValueError, IndexError):
            return "🔄 ซ้ำรายสัปดาห์"
    if recurring.startswith("monthly:"):
        try:
            day = recurring.split(":")[1]
            return f"🔄 ซ้ำทุกวันที่ {day}"
        except IndexError:
            return "🔄 ซ้ำรายเดือน"
    return "🔄 ซ้ำ"


def _next_recurring_deadline(recurring: str, from_utc: datetime) -> Optional[datetime]:
    from_local = pytz.utc.localize(from_utc).astimezone(TZ)
    try:
        if recurring == "daily":
            next_local = from_local + timedelta(days=1)
        elif recurring.startswith("weekly:"):
            target_weekday = int(recurring.split(":")[1])
            days_ahead = (target_weekday - from_local.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            next_local = from_local + timedelta(days=days_ahead)
        elif recurring.startswith("monthly:"):
            target_day = int(recurring.split(":")[1])
            if from_local.month == 12:
                year, month = from_local.year + 1, 1
            else:
                year, month = from_local.year, from_local.month + 1
            max_day = calendar.monthrange(year, month)[1]
            day = min(target_day, max_day)
            next_naive = datetime(year, month, day, from_local.hour, from_local.minute)
            next_local = TZ.localize(next_naive)
        else:
            return None
        return next_local.astimezone(pytz.utc).replace(tzinfo=None)
    except (ValueError, IndexError):
        return None


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


def _task_quick_reply(task_id: int) -> list:
    return [
        {"label": f"✅ เสร็จ #{task_id}", "text": f"เสร็จ {task_id}"},
        {"label": f"📅 เลื่อน #{task_id}", "text": f"เลื่อนงาน {task_id}"},
        {"label": f"🗑️ ลบ #{task_id}", "text": f"ลบ {task_id}"},
    ]


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


def _format_routine_days(days: str) -> str:
    if days == "daily":
        return "ทุกวัน"
    parts = [_ROUTINE_DAY_NAMES.get(d.strip(), d) for d in days.split(",")]
    return "วัน" + "/".join(parts)


def _routine_notify_str(time_hour: int, time_minute: int, advance_minutes: int) -> str:
    dummy = datetime(2000, 1, 1, time_hour, time_minute)
    notify = dummy - timedelta(minutes=advance_minutes)
    suffix = " (วันก่อน)" if notify.date() < dummy.date() else ""
    return f"{notify.hour:02d}:{notify.minute:02d}{suffix}"


# ===== Task handlers =====

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
    db.delete(task)
    db.commit()
    return f"🗑️ ลบแล้ว: #{task_id}"


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


# ===== Routine handlers =====

def _add_routine(
    db: Session, user_id: str, title: str,
    time_hour: int, time_minute: int,
    days: str = "daily", advance_minutes: int = 30,
) -> Routine:
    # Clamp to valid ranges — guard against bad AI output
    time_hour = max(0, min(23, time_hour))
    time_minute = max(0, min(59, time_minute))
    advance_minutes = max(1, min(1440, advance_minutes))
    routine = Routine(
        user_id=user_id, title=title,
        time_hour=time_hour, time_minute=time_minute,
        days=days, advance_minutes=advance_minutes,
    )
    db.add(routine)
    db.commit()
    db.refresh(routine)
    return routine


def _list_routines(db: Session, user_id: str) -> str:
    routines = (
        db.query(Routine)
        .filter_by(user_id=user_id)
        .order_by(Routine.time_hour, Routine.time_minute)
        .all()
    )
    if not routines:
        return "ยังไม่มีกิจวัตร\n💡 เพิ่มได้เลย เช่น 'ออกกำลังกายทุกวัน 18.00'"
    lines = ["🔄 กิจวัตรประจำวัน:"]
    for r in routines:
        notify_str = _routine_notify_str(r.time_hour, r.time_minute, r.advance_minutes)
        lines.append(
            f"#{r.id} {r.title} — {r.time_hour:02d}:{r.time_minute:02d} "
            f"{_format_routine_days(r.days)}\n"
            f"   ⏰ แจ้งเตือนก่อน {r.advance_minutes} นาที ({notify_str})"
        )
    return "\n".join(lines)


def _delete_routine(db: Session, user_id: str, routine_id: int) -> str:
    routine = db.query(Routine).filter_by(id=routine_id, user_id=user_id).first()
    if not routine:
        return f"ไม่เจอกิจวัตร #{routine_id}"
    title = routine.title
    db.delete(routine)
    db.commit()
    return f"🗑️ ลบกิจวัตรแล้ว: #{routine_id} {title}"


def _delete_all_routines(db: Session, user_id: str) -> str:
    n = db.query(Routine).filter_by(user_id=user_id).delete()
    db.commit()
    return f"🗑️ ลบกิจวัตรทั้งหมดแล้ว ({n} รายการ)" if n else "ไม่มีกิจวัตรให้ลบ"


def _update_routine(db: Session, user_id: str, routine_id: int, updates: dict) -> str:
    routine = db.query(Routine).filter_by(id=routine_id, user_id=user_id).first()
    if not routine:
        return f"ไม่เจอกิจวัตร #{routine_id}"
    time_str = updates.get("time")
    if time_str:
        try:
            parts = str(time_str).split(":")
            h, m = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
            routine.time_hour = max(0, min(23, h))
            routine.time_minute = max(0, min(59, m))
        except (ValueError, IndexError):
            pass
    if updates.get("days"):
        routine.days = updates["days"]
    if updates.get("advance_minutes") is not None:
        try:
            routine.advance_minutes = max(1, min(1440, int(updates["advance_minutes"])))
        except (TypeError, ValueError):
            pass
    routine.last_notified_date = None  # reset so new time fires correctly
    db.commit()
    notify_str = _routine_notify_str(routine.time_hour, routine.time_minute, routine.advance_minutes)
    return (
        f"✅ อัปเดตกิจวัตรแล้ว!\n"
        f"🔔 #{routine.id} {routine.title} — "
        f"{routine.time_hour:02d}:{routine.time_minute:02d} {_format_routine_days(routine.days)}\n"
        f"⏰ แจ้งเตือนก่อน {routine.advance_minutes} นาที ({notify_str})"
    )


# ===== Money (รายรับ-รายจ่าย) =====

_SUMMARY_WORDS = ("สรุป", "สรุปรายจ่าย", "สรุปเดือนนี้", "สรุปเงิน", "สรุปรายรับรายจ่าย",
                  "เดือนนี้ใช้ไปเท่าไหร่", "ใช้ไปเท่าไหร่", "ใช้เงินไปเท่าไหร่",
                  "เดือนนี้จ่ายไปเท่าไหร่", "รายจ่ายเดือนนี้", "รายจ่ายเดือน")
_TODAY_MONEY_WORDS = ("รายจ่ายวันนี้", "วันนี้จ่ายอะไรบ้าง", "วันนี้ใช้ไปเท่าไหร่",
                      "จ่ายอะไรไปบ้าง", "รายรับวันนี้", "เงินวันนี้")
_YESTERDAY_MONEY_WORDS = ("รายจ่ายเมื่อวาน", "เมื่อวานใช้ไปเท่าไหร่", "เงินเมื่อวาน",
                          "รายรับเมื่อวาน")


def _local_date_or_none(date_str) -> Optional[datetime]:
    """'2026-08-11' → datetime ตามเวลาไทย (คงเวลาปัจจุบันไว้), ไม่ใช่รูปแบบนี้คืน None"""
    if not isinstance(date_str, str) or len(date_str) < 10:
        return None
    try:
        parsed = datetime.strptime(date_str[:10], "%Y-%m-%d")
    except ValueError:
        return None
    now = now_local()
    return TZ.localize(parsed.replace(hour=now.hour, minute=now.minute))


def _expense_quick_reply(expense_id: int) -> list:
    return [
        {"label": "📊 สรุปเดือนนี้", "text": "สรุป"},
        {"label": "📅 วันนี้", "text": "รายจ่ายวันนี้"},
        {"label": f"🗑️ ลบ #{expense_id}", "text": f"ลบรายจ่าย {expense_id}"},
    ]


def _save_expense(db: Session, user_id: str, parsed: dict, force_kind: Optional[str] = None):
    row = expense.add_expense(
        db, user_id,
        title=parsed["title"],
        amount=parsed["amount"],
        kind=force_kind or parsed["kind"],
        category=expense.guess_category(parsed["title"], force_kind or parsed["kind"]),
        days_offset=parsed.get("days_offset", 0),
    )
    return {"text": expense.format_added(db, user_id, row),
            "quick_reply": _expense_quick_reply(row.id)}


def _delete_expense_reply(db: Session, user_id: str, expense_id: int) -> str:
    row = expense.delete_expense(db, user_id, expense_id)
    if row is None:
        return f"ไม่เจอรายการเงิน #{expense_id} ครับ"
    return f"🗑️ ลบแล้ว: {row.title} {expense.money(row.amount)} บาท"


def _try_expense_command(db: Session, user_id: str, text: str):
    """คำสั่งเกี่ยวกับเงินแบบชัดเจน — ต้องเช็คก่อนคำสั่งงาน (เช่น 'ลบรายจ่าย 3' vs 'ลบ 3')"""
    stripped = text.strip()
    low = stripped.lower()

    for prefix in ("ลบรายจ่าย", "ลบรายรับ", "ลบเงิน"):
        if stripped.startswith(prefix):
            rest = stripped[len(prefix):].strip().lstrip("#")
            if rest.isdigit():
                return _delete_expense_reply(db, user_id, int(rest))
            return "บอก id ของรายการด้วยนะครับ เช่น 'ลบรายจ่าย 3'"

    if low in _SUMMARY_WORDS or stripped in _SUMMARY_WORDS:
        today = now_local()
        return expense.format_month_summary(db, user_id, today.year, today.month)

    if low in _TODAY_MONEY_WORDS:
        return expense.format_day_list(db, user_id, now_local().date(), "📅 เงินวันนี้")

    if low in _YESTERDAY_MONEY_WORDS:
        yesterday = (now_local() - timedelta(days=1)).date()
        return expense.format_day_list(db, user_id, yesterday, "📅 เงินเมื่อวาน")

    # "รายจ่าย <ของ> <ราคา>" / "รายรับ <ที่มา> <จำนวน>" — ระบุชนิดชัดเจน
    for prefix, kind in (("รายจ่าย", "expense"), ("รายรับ", "income")):
        if stripped.startswith(prefix):
            rest = stripped[len(prefix):].strip()
            if not rest:
                continue
            parsed = expense.parse_expense(rest)
            if parsed:
                return _save_expense(db, user_id, parsed, force_kind=kind)

    return None


def _try_expense_add(db: Session, user_id: str, text: str):
    """ตัวสุดท้ายของ strict pipeline — ถ้าไม่ใช่คำสั่งงานใดๆ เลย ลองอ่านเป็นเงิน"""
    parsed = expense.parse_expense(text)
    if not parsed:
        return None
    return _save_expense(db, user_id, parsed)


# ===== Strict pattern matcher =====

_THAI_TIME_WORDS = ("ทุ่ม", "บ่าย", "เย็น", "ตี ", "ตี1", "ตี2", "ตี3", "ตี4", "ตี5",
                    "เช้า", "เที่ยง", "ค่ำ", "ดึก", "สาย", "โมง")

_LIST_QUESTION_WORDS = ("มีอะไร", "ดูงาน", "งาน", "list", "today", "tomorrow", "บ้าง")


def _looks_like_schedule_statement(text: str, lower: str) -> bool:
    has_day = any(w in text for w in ("วันนี้", "พรุ่งนี้", "มะรืน")) or "tomorrow" in lower
    has_time = any(w in text for w in _THAI_TIME_WORDS) or ":" in text or "." in text
    has_verb = any(w in text for w in ("มี", "ต้อง", "นัด", "ประชุม", "ส่ง", "ทำ", "ออก", "กิน", "เตือน"))
    is_list_question = any(w in text for w in _LIST_QUESTION_WORDS) and not has_time
    return has_day and has_time and has_verb and not is_list_question


# ===== Clarify (pending) state =====

def _set_pending(db: Session, user_id: str, title: str) -> None:
    """Remember a task whose date/time we just asked the user for (upsert)."""
    row = db.query(PendingClarify).filter_by(user_id=user_id).first()
    if row:
        row.title = title[:500]
        row.created_at = datetime.utcnow()
    else:
        db.add(PendingClarify(user_id=user_id, title=title[:500]))
    db.commit()


def _get_pending(db: Session, user_id: str) -> Optional[PendingClarify]:
    """Return an unexpired pending clarify, or None. Expired rows are cleaned up."""
    row = db.query(PendingClarify).filter_by(user_id=user_id).first()
    if not row:
        return None
    if datetime.utcnow() - row.created_at > timedelta(minutes=_PENDING_TTL_MIN):
        _clear_pending(db, user_id)
        return None
    return row


def _clear_pending(db: Session, user_id: str) -> None:
    db.query(PendingClarify).filter_by(user_id=user_id).delete()
    db.commit()


# Unmistakable standalone commands that should override a pending clarify
# (the user asked something else instead of supplying the missing date).
_FRESH_COMMANDS = {
    "วันนี้", "today", "งานวันนี้", "ดูงานวันนี้",
    "ทั้งหมด", "all", "list", "งานทั้งหมด", "ดูงานทั้งหมด",
    "กิจวัตร", "กิจวัตรของฉัน", "routine", "routines",
    "ช่วยเหลือ", "help", "?",
}


def _looks_like_fresh_command(text: str) -> bool:
    """Whole-message match only — never treat a date answer as a command."""
    return text.strip().lower() in _FRESH_COMMANDS


def _log_unknown(db: Session, user_id: str, text: str, ai_intent: str = "unknown") -> None:
    """Save unrecognized messages for later review and bot improvement."""
    try:
        msg = UnknownMessage(user_id=user_id, text=text[:1000], ai_intent=ai_intent)
        db.add(msg)
        db.commit()
    except Exception as e:
        print(f"[unknown_log] failed: {e}")


def _try_strict(db: Session, user_id: str, text: str) -> Optional[str]:
    lower = text.lower()

    # เงินก่อน: "ลบรายจ่าย 3" ต้องไม่ตกไปเข้าเงื่อนไข "ลบ" ของงาน
    money_cmd = _try_expense_command(db, user_id, text)
    if money_cmd is not None:
        return money_cmd

    if text.startswith("เพิ่ม") or lower.startswith("add "):
        body = text[len("เพิ่ม"):].strip() if text.startswith("เพิ่ม") else text[4:].strip()
        if not body:
            return "พิมพ์ชื่องานด้วยนะครับ\nเช่น: เพิ่ม ส่งรายงาน พรุ่งนี้ 18:00"
        if any(w in body for w in _THAI_TIME_WORDS) and ai_parser.is_enabled():
            return None
        title, deadline = parse_task(body)
        if not title:
            return "ไม่เจอชื่องาน ลองพิมพ์ใหม่นะครับ"
        task = _add_task(db, user_id, title, deadline)
        return _format_add_beautiful(db, user_id, task)

    if text in ("วันนี้", "today", "งานวันนี้", "ดูงานวันนี้"):
        return _list_today(db, user_id)

    if _looks_like_schedule_statement(text, lower):
        return None

    if ("พรุ่งนี้" in text or "tomorrow" in lower) and ("ลบ" not in text and "เพิ่ม" not in text):
        return _list_tomorrow(db, user_id)

    if (any(w in text for w in ("อาทิต", "สัปดาห์", "week")) and
            ("ลบ" not in text and "เพิ่ม" not in text)):
        return _list_this_week(db, user_id)

    if any(w in text for w in ("ค้าง", "เลยกำหนด", "overdue", "เกินกำหนด")):
        return _list_overdue(db, user_id)

    if any(w in text for w in ("ด่วน", "urgent", "สำคัญ", "งานด่วน")):
        return _list_urgent(db, user_id)

    if text.startswith("หางาน") or text.startswith("ค้นหา") or lower.startswith("search "):
        kw = text[len("หางาน"):].strip() if text.startswith("หางาน") else \
             text[len("ค้นหา"):].strip() if text.startswith("ค้นหา") else \
             text[7:].strip()
        if kw:
            return _search_tasks(db, user_id, kw)
        return None

    if text.startswith("โน้ต") or text.startswith("เพิ่มโน้ต"):
        prefix = "เพิ่มโน้ต" if text.startswith("เพิ่มโน้ต") else "โน้ต"
        rest = text[len(prefix):].strip()
        parts = rest.split(" ", 1)
        if len(parts) == 2 and parts[0].isdigit():
            return _add_note(db, user_id, int(parts[0]), parts[1])
        return None

    if text in ("ทั้งหมด", "all", "list", "งานทั้งหมด", "ดูงานทั้งหมด"):
        return _list_all(db, user_id)

    if text.startswith("เสร็จ") or lower.startswith("done "):
        rest = text[len("เสร็จ"):].strip() if text.startswith("เสร็จ") else text[5:].strip()
        if rest.isdigit():
            return _mark_done(db, user_id, int(rest))
        return None

    if text in ("ลบกิจวัตรทั้งหมด", "ลบกิจวัตรหมด"):
        return _delete_all_routines(db, user_id)

    if text.startswith("ลบกิจวัตร"):
        rest = text[len("ลบกิจวัตร"):].strip()
        if rest.isdigit():
            return _delete_routine(db, user_id, int(rest))
        return None

    if text in ("กิจวัตร", "กิจวัตรของฉัน", "routine", "routines"):
        return _list_routines(db, user_id)

    if text.startswith("ลบ") or lower.startswith("del ") or lower.startswith("delete "):
        if text.startswith("ลบ"):
            rest = text[len("ลบ"):].strip()
        elif lower.startswith("del "):
            rest = text[4:].strip()
        else:
            rest = text[7:].strip()
        if rest.isdigit():
            return _delete_task(db, user_id, int(rest))
        return None

    if text.startswith("ยกเลิกซ้ำ"):
        rest = text[len("ยกเลิกซ้ำ"):].strip()
        if rest.isdigit():
            return _cancel_recurring(db, user_id, int(rest))
        return None

    if text in ("ช่วยเหลือ", "help", "?"):
        return HELP_TEXT

    # ท้ายสุด: ไม่ใช่คำสั่งงานเลย → ลองอ่านเป็นเงิน ("กาแฟ 60")
    return _try_expense_add(db, user_id, text)


# ===== AI dispatcher =====

def _dispatch_ai(db: Session, user_id: str, intent: dict, allow_clarify: bool = True):
    action = intent.get("intent", "unknown")
    extra = intent.get("reply", "")

    if action == "clarify":
        tasks_raw = intent.get("tasks")
        tasks_in = tasks_raw if isinstance(tasks_raw, list) else []
        title = ""
        for t in tasks_in:
            if isinstance(t, dict) and (t.get("title") or "").strip():
                title = t["title"].strip()
                break
        if not title:
            return extra or "บอกชื่องานที่จะเตือนด้วยนะครับ"
        if not allow_clarify:
            # This is already the user's answer and it's still missing a time —
            # don't ask again (avoid loops). Just add the task without a deadline.
            saved = _add_task(db, user_id, title, None)
            return _format_add_beautiful(db, user_id, saved)
        _set_pending(db, user_id, title)
        return (
            (extra.strip() if extra else f"📅 อยากให้เตือน \"{title}\" วันไหน เวลาไหนดีครับ?")
            + "\n(ตอบเช่น 'พรุ่งนี้ 17:00' หรือพิมพ์ 'ยกเลิก')"
        )

    if action == "add":
        tasks_raw = intent.get("tasks")
        tasks_in = tasks_raw if isinstance(tasks_raw, list) else []
        if not tasks_in:
            return "ไม่เจอชื่องาน ลองพิมพ์ใหม่นะครับ"
        added = []
        for t in tasks_in:
            if not isinstance(t, dict):
                continue
            title = (t.get("title") or "").strip()
            if not title:
                continue
            deadline = _ai_deadline_to_utc(t.get("deadline"))
            recurring = t.get("recurring") or None
            priority = (t.get("priority") or "normal").strip().lower()
            note = t.get("note") or None
            saved = _add_task(db, user_id, title, deadline, recurring, priority, note)
            added.append(saved)
        if not added:
            return "ไม่เจอชื่องาน ลองพิมพ์ใหม่นะครับ"
        if len(added) == 1:
            return _format_add_beautiful(db, user_id, added[0])
        lines = ["✅ เพิ่มงานแล้ว"] + [_format_task_line(t) for t in added]
        return "\n".join(lines)

    if action == "list_today":
        return _list_today(db, user_id)

    if action == "list_tomorrow":
        return _list_tomorrow(db, user_id)

    if action == "list_week":
        return _list_this_week(db, user_id)

    if action == "list_overdue":
        return _list_overdue(db, user_id)

    if action == "list_date":
        date_str = intent.get("date") or ""
        return _list_date(db, user_id, str(date_str))

    if action == "list_urgent":
        return _list_urgent(db, user_id)

    if action == "list_all":
        return _list_all(db, user_id)

    if action == "search":
        kw = (intent.get("keyword") or "").strip()
        return _search_tasks(db, user_id, kw)

    if action == "add_note":
        tid = intent.get("task_id")
        note_text = (intent.get("note") or "").strip()
        if isinstance(tid, int) and note_text:
            return _add_note(db, user_id, tid, note_text)
        return "บอก id งานและโน้ตด้วยนะครับ เช่น 'เพิ่มโน้ต 3 ว่า ติดต่อต้น'"

    if action == "set_priority":
        tid = intent.get("task_id")
        p = (intent.get("priority") or "normal").strip().lower()
        if isinstance(tid, int):
            return _set_priority(db, user_id, tid, p)
        return "บอก id งานด้วยนะครับ เช่น 'ตั้ง priority งาน 3 เป็น urgent'"

    if action == "snooze":
        tid = intent.get("task_id")
        dl = intent.get("deadline")
        if isinstance(tid, int):
            return _snooze_task(db, user_id, tid, dl)
        return "บอก id งานและวันที่ใหม่ด้วยนะครับ เช่น 'เลื่อนงาน 3 เป็นพรุ่งนี้ 18:00'"

    if action == "update_routine":
        rid = intent.get("routine_id")
        r_raw = intent.get("routine")
        updates = r_raw if isinstance(r_raw, dict) else {}
        if isinstance(rid, int):
            return _update_routine(db, user_id, rid, updates)
        return "บอก id กิจวัตรด้วยนะครับ เช่น 'แก้กิจวัตร 1 เป็น 19:00'"

    if action == "done":
        tid = intent.get("task_id")
        if isinstance(tid, int):
            return _mark_done(db, user_id, tid)
        return "บอก id งานที่เสร็จด้วยนะครับ เช่น 'เสร็จ 3'"

    if action == "delete":
        tid = intent.get("task_id")
        if isinstance(tid, int):
            return _delete_task(db, user_id, tid)
        return "บอก id งานที่จะลบด้วยนะครับ เช่น 'ลบ 3'"

    if action == "delete_all":
        return _delete_all(db, user_id)

    if action == "done_all":
        return _done_all(db, user_id)

    if action == "cancel_recurring":
        tid = intent.get("task_id")
        if isinstance(tid, int):
            return _cancel_recurring(db, user_id, tid)
        return "บอก id งานที่จะยกเลิกซ้ำด้วยนะครับ เช่น 'ยกเลิกซ้ำ 3'"

    if action == "add_routine":
        r_raw = intent.get("routine")
        r = r_raw if isinstance(r_raw, dict) else {}
        title = (r.get("title") or "").strip()
        if not title:
            return "ไม่เจอชื่อกิจวัตร ลองพิมพ์ใหม่นะครับ\nเช่น 'ออกกำลังกายทุกวัน 18.00'"
        time_str = (r.get("time") or "08:00").strip()
        try:
            parts = time_str.split(":")
            h, m = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
        except (ValueError, IndexError):
            h, m = 8, 0
        days = (r.get("days") or "daily").strip()
        if not days:
            days = "daily"
        try:
            advance = int(r.get("advance_minutes") or 30)
        except (TypeError, ValueError):
            advance = 30
        saved = _add_routine(db, user_id, title, h, m, days, advance)
        notify_str = _routine_notify_str(saved.time_hour, saved.time_minute, saved.advance_minutes)
        return (
            f"✅ เพิ่มกิจวัตรแล้ว!\n"
            f"🔔 #{saved.id} {saved.title} — {saved.time_hour:02d}:{saved.time_minute:02d} "
            f"{_format_routine_days(saved.days)}\n"
            f"⏰ จะแจ้งเตือนก่อน {saved.advance_minutes} นาที ({notify_str})"
        )

    if action == "list_routines":
        return _list_routines(db, user_id)

    if action == "delete_routine":
        rid = intent.get("routine_id")
        if isinstance(rid, int):
            return _delete_routine(db, user_id, rid)
        return "บอก id กิจวัตรที่จะลบด้วยนะครับ เช่น 'ลบกิจวัตร 1'"

    if action == "delete_all_routines":
        return _delete_all_routines(db, user_id)

    if action == "expense":
        raw = intent.get("expenses")
        rows = []
        for item in (raw if isinstance(raw, list) else []):
            if not isinstance(item, dict):
                continue
            title = (item.get("title") or "").strip()
            try:
                amount = float(item.get("amount"))
            except (TypeError, ValueError):
                continue
            if not title or amount <= 0:
                continue
            kind = "income" if item.get("kind") == "income" else "expense"
            rows.append(expense.add_expense(
                db, user_id, title=title, amount=amount, kind=kind,
                spent_at_local=_local_date_or_none(item.get("date")),
            ))
        if not rows:
            return "ไม่เจอจำนวนเงินครับ ลองพิมพ์แบบ 'กาแฟ 60' ดูนะ"
        if len(rows) == 1:
            return {"text": expense.format_added(db, user_id, rows[0]),
                    "quick_reply": _expense_quick_reply(rows[0].id)}
        total = sum(r.amount for r in rows if r.kind == "expense")
        lines = ["✅ บันทึกแล้ว %d รายการ" % len(rows), ""]
        lines += [expense.format_entry_line(r) for r in rows]
        lines.append("")
        lines.append(f"รวมจ่าย {expense.money(total)} บาท")
        return {"text": "\n".join(lines), "quick_reply": _expense_quick_reply(rows[-1].id)}

    if action == "expense_summary":
        month_str = intent.get("month")
        target = now_local()
        if isinstance(month_str, str) and len(month_str) >= 7:
            try:
                target = target.replace(year=int(month_str[:4]), month=int(month_str[5:7]), day=1)
            except ValueError:
                pass
        return expense.format_month_summary(db, user_id, target.year, target.month)

    if action == "expense_list":
        when = _local_date_or_none(intent.get("date")) or now_local()
        return expense.format_day_list(db, user_id, when.date(),
                                       f"📅 เงินวันที่ {when.strftime('%d/%m')}")

    if action == "expense_delete":
        eid = intent.get("expense_id")
        if isinstance(eid, int):
            return _delete_expense_reply(db, user_id, eid)
        return "บอก id ของรายการที่จะลบด้วยนะครับ เช่น 'ลบรายจ่าย 3'"

    if action == "help":
        return HELP_TEXT

    # Unknown intent — log for self-improvement review
    _log_unknown(db, user_id, intent.get("_original_text", ""), action)
    if extra:
        return f"{extra}\n\n{HELP_TEXT}"
    return HELP_TEXT


# ===== Public entry point =====

def _run_pipeline(db: Session, user_id: str, text: str, allow_clarify: bool = True):
    strict = _try_strict(db, user_id, text)
    if strict is not None:
        return strict

    if ai_parser.is_enabled():
        intent = ai_parser.parse(text)
        intent["_original_text"] = text  # pass through for unknown logging
        return _dispatch_ai(db, user_id, intent, allow_clarify=allow_clarify)

    # Strict parser only, no AI — log as unknown
    _log_unknown(db, user_id, text, "no_ai")
    return HELP_TEXT


def handle_command(db: Session, user_id: str, text: str):
    text = text.strip()
    if not text:
        return HELP_TEXT

    # If we previously asked the user for a missing date/time, treat this message
    # as the answer: merge it with the remembered task title and run it through
    # the normal pipeline (which parses the date). allow_clarify=False so we never
    # loop back into another question.
    pending = _get_pending(db, user_id)
    if pending is not None:
        _clear_pending(db, user_id)
        if _is_cancel(text):
            return f"โอเค ยกเลิก \"{pending.title}\" แล้วนะครับ 👍"
        # If the reply is itself an unmistakable command (list/help/etc.), the user
        # has moved on — run it fresh instead of treating it as the missing date.
        if _looks_like_fresh_command(text):
            return _run_pipeline(db, user_id, text, allow_clarify=True)
        combined = f"เพิ่ม {pending.title} {text}".strip()
        return _run_pipeline(db, user_id, combined, allow_clarify=False)

    return _run_pipeline(db, user_id, text, allow_clarify=True)

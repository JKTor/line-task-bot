"""Handle text commands from LINE users.

Strategy: try strict pattern matching first (fast, free, predictable).
If nothing matches and AI is configured, fall back to AI parsing.
"""
import calendar
from datetime import datetime, timedelta
from typing import List, Optional

import pytz
from sqlalchemy.orm import Session

from app import ai_parser
from app.models import Routine, Task
from app.parser import TZ, format_deadline, now_local, parse_task

HELP_TEXT = (
    "📝 คำสั่งที่ใช้ได้:\n"
    "• เพิ่ม <งาน> [วันเวลา] — เช่น เพิ่ม ส่งรายงาน พรุ่งนี้ 18:00\n"
    "• วันนี้ — ดูงานวันนี้\n"
    "• ทั้งหมด — ดูงานที่ยังไม่เสร็จ\n"
    "• เสร็จ <id> — ทำเครื่องหมายเสร็จ\n"
    "• ลบ <id> — ลบงาน\n"
    "• ยกเลิกซ้ำ <id> — หยุดการทำซ้ำ\n"
    "• กิจวัตร — ดูกิจวัตรประจำวัน\n"
    "• ลบกิจวัตร <id> — ลบกิจวัตร\n"
    "• ลบกิจวัตรทั้งหมด — ลบกิจวัตรทั้งหมด\n"
    "• ช่วยเหลือ — แสดงคำสั่งทั้งหมด\n\n"
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

def _format_task_line(t: Task) -> str:
    mark = "✅" if t.done else "⬜"
    recur = " 🔄" if t.recurring else ""
    return f"{mark} #{t.id} {t.title}{recur}  ⏰ {format_deadline(t.deadline)}"


def _list_message(tasks: List[Task], header: str) -> str:
    if not tasks:
        return f"{header}\n(ไม่มีงาน 🎉)"
    return "\n".join([header] + [_format_task_line(t) for t in tasks])


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


def _format_add_beautiful(db: Session, user_id: str, new_task: Task) -> str:
    recur_str = f"\n{_recurring_label(new_task.recurring)}" if new_task.recurring else ""
    if not new_task.deadline:
        return f"✅ เพิ่มงานแล้ว!\n📋 #{new_task.id} {new_task.title}{recur_str}\n(ไม่มีกำหนดส่ง)"
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
    return f"✅ เพิ่มงานแล้ว!\n\n{added_block}{summary}\n\n💪 สู้ๆ นะ!"


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
              recurring: Optional[str] = None) -> Task:
    task = Task(user_id=user_id, title=title, deadline=deadline, recurring=recurring)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def _list_today(db: Session, user_id: str) -> str:
    today_local = now_local().date()
    start_local = now_local().replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
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
    return _list_message(tasks, f"📅 งานวันนี้ ({today_local.strftime('%d/%m')})")


def _list_all(db: Session, user_id: str) -> str:
    tasks = (
        db.query(Task)
        .filter(Task.user_id == user_id, Task.done == False)  # noqa: E712
        .order_by(Task.deadline.is_(None), Task.deadline.asc())
        .all()
    )
    return _list_message(tasks, "📋 งานที่ยังไม่เสร็จ")


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


# ===== Strict pattern matcher =====

_THAI_TIME_WORDS = ("ทุ่ม", "บ่าย", "เย็น", "ตี ", "ตี1", "ตี2", "ตี3", "ตี4", "ตี5",
                    "เช้า", "เที่ยง", "ค่ำ", "ดึก", "สาย", "โมง")


def _try_strict(db: Session, user_id: str, text: str) -> Optional[str]:
    lower = text.lower()

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

    if text in ("วันนี้", "today"):
        return _list_today(db, user_id)

    if text in ("ทั้งหมด", "all", "list"):
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

    return None


# ===== AI dispatcher =====

def _dispatch_ai(db: Session, user_id: str, intent: dict) -> str:
    action = intent.get("intent", "unknown")
    extra = intent.get("reply", "")

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
            saved = _add_task(db, user_id, title, deadline, recurring)
            added.append(saved)
        if not added:
            return "ไม่เจอชื่องาน ลองพิมพ์ใหม่นะครับ"
        if len(added) == 1:
            return _format_add_beautiful(db, user_id, added[0])
        lines = ["✅ เพิ่มงานแล้ว"] + [_format_task_line(t) for t in added]
        return "\n".join(lines)

    if action == "list_today":
        return _list_today(db, user_id)

    if action == "list_all":
        return _list_all(db, user_id)

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

    if action == "help":
        return HELP_TEXT

    if extra:
        return f"{extra}\n\n{HELP_TEXT}"
    return HELP_TEXT


# ===== Public entry point =====

def handle_command(db: Session, user_id: str, text: str) -> str:
    text = text.strip()
    if not text:
        return HELP_TEXT

    strict = _try_strict(db, user_id, text)
    if strict is not None:
        return strict

    if ai_parser.is_enabled():
        intent = ai_parser.parse(text)
        return _dispatch_ai(db, user_id, intent)

    return HELP_TEXT

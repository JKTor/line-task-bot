"""Handle text commands from LINE users.

Strategy: try strict pattern matching first (fast, free, predictable).
If nothing matches and Gemini is configured, fall back to AI parsing.
"""
from datetime import datetime, timedelta
from typing import List, Optional

import pytz
from sqlalchemy.orm import Session

from app import ai_parser
from app.models import Task
from app.parser import TZ, format_deadline, now_local, parse_task

HELP_TEXT = (
    "📝 คำสั่งที่ใช้ได้:\n"
    "• เพิ่ม <งาน> [วันเวลา] — เช่น เพิ่ม ส่งรายงาน พรุ่งนี้ 18:00\n"
    "• วันนี้ — ดูงานวันนี้\n"
    "• ทั้งหมด — ดูงานที่ยังไม่เสร็จ\n"
    "• เสร็จ <id> — ทำเครื่องหมายเสร็จ\n"
    "• ลบ <id> — ลบงาน\n"
    "• ช่วยเหลือ — แสดงคำสั่งทั้งหมด\n\n"
    "💡 พิมพ์ธรรมชาติก็ได้ เช่น 'พรุ่งนี้ลืมส่งรายงาน 6 โมงเย็น'"
)

THAI_MONTHS = ["","ม.ค.","ก.พ.","มี.ค.","เม.ย.","พ.ค.","มิ.ย.",
               "ก.ค.","ส.ค.","ก.ย.","ต.ค.","พ.ย.","ธ.ค."]

NUMBERED = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]


# ===== Helpers =====

def _format_task_line(t: Task) -> str:
    mark = "✅" if t.done else "⬜"
    return f"{mark} #{t.id} {t.title}  ⏰ {format_deadline(t.deadline)}"


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
    if not new_task.deadline:
        return f"✅ เพิ่มงานแล้ว!\n📋 #{new_task.id} {new_task.title}\n(ไม่มีกำหนดส่ง)"
    local_dt = pytz.utc.localize(new_task.deadline).astimezone(TZ)
    target_date = local_dt.date()
    label = _label_for_date(target_date)
    time_str = local_dt.strftime("%H:%M")
    added_block = (
        f"〰〰〰〰〰〰〰〰〰〰\n"
        f"📌 งานที่เพิ่ม:\n"
        f"📋 {new_task.title}\n"
        f"📅 {label} | 🕒 {time_str} น.\n"
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
            lines.append(f"{num} {t.title} — {t_local.strftime('%H:%M')} น.")
        summary = "\n".join(lines)
    return f"✅ เพิ่มงานแล้ว!\n\n{added_block}{summary}\n\n💪 สู้ๆ นะ!"


# ===== Action handlers =====

def _add_task(db: Session, user_id: str, title: str, deadline: Optional[datetime]) -> Task:
    task = Task(user_id=user_id, title=title, deadline=deadline)
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
    task.done = True
    db.commit()
    return f"🎉 ทำเครื่องหมายเสร็จแล้ว: #{task.id} {task.title}"


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
        .update({Task.done: True})
    )
    db.commit()
    return f"🎉 ปิดงานทั้งหมดแล้ว ({n} รายการ)" if n else "ไม่มีงานที่ค้างอยู่"


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

    if text in ("ช่วยเหลือ", "help", "?"):
        return HELP_TEXT

    return None


# ===== AI dispatcher =====

def _dispatch_ai(db: Session, user_id: str, intent: dict) -> str:
    action = intent.get("intent", "unknown")
    extra = intent.get("reply", "")

    if action == "add":
        tasks_in = intent.get("tasks") or []
        if not tasks_in:
            return "ไม่เจอชื่องาน ลองพิมพ์ใหม่นะครับ"
        added = []
        for t in tasks_in:
            title = (t.get("title") or "").strip()
            if not title:
                continue
            deadline = _ai_deadline_to_utc(t.get("deadline"))
            saved = _add_task(db, user_id, title, deadline)
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

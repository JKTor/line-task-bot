"""Handle text commands from LINE users."""
from datetime import timedelta
from typing import List

from sqlalchemy.orm import Session

from app.models import Task
from app.parser import format_deadline, now_local, parse_task

HELP_TEXT = (
    "📝 คำสั่งที่ใช้ได้:\n"
    "• เพิ่ม <งาน> [วันเวลา]\n"
    "   เช่น: เพิ่ม ส่งรายงาน 10/5 18:00\n"
    "   หรือ: เพิ่ม ประชุม พรุ่งนี้ 10:00\n"
    "• วันนี้ — ดูงานวันนี้\n"
    "• ทั้งหมด — ดูงานที่ยังไม่เสร็จ\n"
    "• เสร็จ <id> — ทำเครื่องหมายเสร็จ\n"
    "• ลบ <id> — ลบงาน\n"
    "• ช่วยเหลือ — แสดงคำสั่งทั้งหมด"
)


def _format_task_line(t: Task) -> str:
    mark = "✅" if t.done else "⬜"
    return f"{mark} #{t.id} {t.title}  ⏰ {format_deadline(t.deadline)}"


def _list_tasks(tasks: List[Task], header: str) -> str:
    if not tasks:
        return f"{header}\n(ไม่มีงาน 🎉)"
    lines = [header] + [_format_task_line(t) for t in tasks]
    return "\n".join(lines)


def handle_command(db: Session, user_id: str, text: str) -> str:
    text = text.strip()
    if not text:
        return HELP_TEXT

    lower = text.lower()

    # ----- Add task -----
    if text.startswith("เพิ่ม") or lower.startswith("add "):
        body = text[len("เพิ่ม"):].strip() if text.startswith("เพิ่ม") else text[4:].strip()
        if not body:
            return "พิมพ์ชื่องานด้วยนะครับ\nเช่น: เพิ่ม ส่งรายงาน พรุ่งนี้ 18:00"
        title, deadline = parse_task(body)
        if not title:
            return "ไม่เจอชื่องาน ลองพิมพ์ใหม่นะครับ"
        task = Task(user_id=user_id, title=title, deadline=deadline)
        db.add(task)
        db.commit()
        db.refresh(task)
        return f"✅ เพิ่มงานแล้ว\n#{task.id} {task.title}\n⏰ {format_deadline(task.deadline)}"

    # ----- Today's tasks -----
    if text in ("วันนี้", "today"):
        today_local = now_local().date()
        # Build UTC range for "today" in Bangkok
        start_local = now_local().replace(hour=0, minute=0, second=0, microsecond=0)
        end_local = start_local + timedelta(days=1)
        import pytz
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
        return _list_tasks(tasks, f"📅 งานวันนี้ ({today_local.strftime('%d/%m')})")

    # ----- All open tasks -----
    if text in ("ทั้งหมด", "all", "list"):
        tasks = (
            db.query(Task)
            .filter(Task.user_id == user_id, Task.done == False)  # noqa: E712
            .order_by(Task.deadline.is_(None), Task.deadline.asc())
            .all()
        )
        return _list_tasks(tasks, "📋 งานที่ยังไม่เสร็จ")

    # ----- Mark done -----
    if text.startswith("เสร็จ") or lower.startswith("done "):
        rest = text[len("เสร็จ"):].strip() if text.startswith("เสร็จ") else text[5:].strip()
        if not rest.isdigit():
            return "พิมพ์ id งานด้วยครับ เช่น: เสร็จ 3"
        task = db.query(Task).filter_by(id=int(rest), user_id=user_id).first()
        if not task:
            return f"ไม่เจองาน #{rest}"
        task.done = True
        db.commit()
        return f"🎉 ทำเครื่องหมายเสร็จแล้ว: #{task.id} {task.title}"

    # ----- Delete -----
    if text.startswith("ลบ") or lower.startswith("del ") or lower.startswith("delete "):
        if text.startswith("ลบ"):
            rest = text[len("ลบ"):].strip()
        elif lower.startswith("del "):
            rest = text[4:].strip()
        else:
            rest = text[7:].strip()
        if not rest.isdigit():
            return "พิมพ์ id งานด้วยครับ เช่น: ลบ 3"
        task = db.query(Task).filter_by(id=int(rest), user_id=user_id).first()
        if not task:
            return f"ไม่เจองาน #{rest}"
        db.delete(task)
        db.commit()
        return f"🗑️ ลบแล้ว: #{rest}"

    # ----- Help / default -----
    if text in ("ช่วยเหลือ", "help", "?"):
        return HELP_TEXT

    return HELP_TEXT

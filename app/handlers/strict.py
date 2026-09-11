"""ชั้นที่ 1 ของสายอ่านข้อความ — จับรูปประโยคตายตัวด้วย pattern ล้วน

เร็ว ฟรี และได้ผลเหมือนเดิมทุกครั้ง อ่านไม่ออกเมื่อไหร่คืน None เพื่อให้ router
ส่งต่อไปชั้น AI — ข้อความส่วนใหญ่จบที่ชั้นนี้ ไม่ต้องเรียก AI เลย
"""
from typing import Optional

from sqlalchemy.orm import Session

from app import ai_parser
from app.handlers.constants import HELP_TEXT
from app.handlers.money import _delete_smart, _try_expense_add, _try_expense_command
from app.handlers.routines import (
    _delete_all_routines,
    _delete_routine,
    _list_routines,
)
from app.handlers.tasks import (
    _add_note,
    _add_task,
    _cancel_recurring,
    _delete_task,
    _format_add_beautiful,
    _list_all,
    _list_overdue,
    _list_this_week,
    _list_today,
    _list_tomorrow,
    _list_urgent,
    _mark_done,
    _search_tasks,
)
from app.parser import parse_task

_THAI_TIME_WORDS = ("ทุ่ม", "บ่าย", "เย็น", "ตี ", "ตี1", "ตี2", "ตี3", "ตี4", "ตี5",
                    "เช้า", "เที่ยง", "ค่ำ", "ดึก", "สาย", "โมง")

_LIST_QUESTION_WORDS = ("มีอะไร", "ดูงาน", "งาน", "list", "today", "tomorrow", "บ้าง")


def _looks_like_schedule_statement(text: str, lower: str) -> bool:
    has_day = any(w in text for w in ("วันนี้", "พรุ่งนี้", "มะรืน")) or "tomorrow" in lower
    has_time = any(w in text for w in _THAI_TIME_WORDS) or ":" in text or "." in text
    has_verb = any(w in text for w in ("มี", "ต้อง", "นัด", "ประชุม", "ส่ง", "ทำ", "ออก", "กิน", "เตือน"))
    is_list_question = any(w in text for w in _LIST_QUESTION_WORDS) and not has_time
    return has_day and has_time and has_verb and not is_list_question

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

    if text.startswith("ลบงาน"):
        rest = text[len("ลบงาน"):].strip().lstrip("#")
        if rest.isdigit():
            return _delete_task(db, user_id, int(rest))
        return None

    if text.startswith("ลบ") or lower.startswith("del ") or lower.startswith("delete "):
        if text.startswith("ลบ"):
            rest = text[len("ลบ"):].strip()
        elif lower.startswith("del "):
            rest = text[4:].strip()
        else:
            rest = text[7:].strip()
        rest = rest.lstrip("#")
        if rest.isdigit():
            return _delete_smart(db, user_id, int(rest))
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

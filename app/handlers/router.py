"""ทางเข้าเดียวของข้อความจาก LINE — ตัดสินว่าจะส่งข้อความไปชั้นไหน

    handle_command
      +- มีสถานะรอคำตอบค้างอยู่ไหม -> ถ้ามี เอาคำตอบไปต่อกับหัวข้องานที่จำไว้
      +- _run_pipeline
           +- ชั้น 1 strict (pattern) -- ข้อความส่วนใหญ่จบตรงนี้
           +- ชั้น 2 AI               -- เฉพาะที่ชั้น 1 อ่านไม่ออก
"""
from sqlalchemy.orm import Session

from app import ai_parser
from app.handlers.ai_dispatch import _dispatch_ai
from app.handlers.clarify import (
    _clear_pending,
    _get_pending,
    _is_cancel,
    _log_unknown,
    _looks_like_fresh_command,
)
from app.handlers.constants import HELP_TEXT
from app.handlers.strict import _try_strict

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

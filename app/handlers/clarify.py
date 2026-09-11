"""สถานะ 'ถามกลับแล้วรอคำตอบ' + บันทึกข้อความที่ระบบอ่านไม่ออก

ตอนบอทถามว่า 'งานนี้เอาวันไหน?' ต้องจำหัวข้องานไว้ระหว่างรอคำตอบ สถานะนี้หมดอายุ
ใน 10 นาที เพื่อไม่ให้ข้อความที่ผู้ใช้พิมพ์ทีหลังถูกนับเป็นคำตอบของคำถามเก่า
"""
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models import PendingClarify, UnknownMessage

# How long a "waiting for the user to supply a date" state stays valid.
_PENDING_TTL_MIN = 10
# Match cancel only against the *whole* short reply — never as a substring.
# ("เลิก" as a substring would wrongly cancel answers like "หลังเลิกงาน 6 โมง".)
_CANCEL_WORDS = {"ยกเลิก", "ไม่ต้อง", "ไม่ต้องแล้ว", "ไม่เอา", "ไม่เอาแล้ว", "เลิก", "cancel"}


def _is_cancel(text: str) -> bool:
    t = text.strip().lower()
    return t in _CANCEL_WORDS or t.startswith("ยกเลิก")

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

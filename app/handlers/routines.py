"""กิจวัตรประจำวัน (Routine) — เพิ่ม / ดู / แก้ / ลบ

ต่างจากงาน (Task) ตรงที่กิจวัตรไม่มีวันครบกำหนดและไม่ต้องกดว่าเสร็จ แค่เตือนตามเวลา
"""
from typing import List

from sqlalchemy.orm import Session

from app.handlers.formatting import _format_routine_days, _routine_notify_str
from app.models import Routine

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

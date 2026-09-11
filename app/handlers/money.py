"""รายรับ-รายจ่าย — บันทึก / สรุป / ลบ

`_delete_smart` อยู่ไฟล์นี้เพราะเป็นจุดที่งานกับรายการเงินชนกัน: สองตารางนับ id คนละชุด
เลข #3 จึงเป็นได้ทั้งงานและรายจ่าย ถ้าซ้ำต้องถามก่อน ห้ามเดา
"""
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app import expense
from app.handlers.tasks import _delete_task
from app.models import Expense, Task
from app.parser import TZ, now_local

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


def _delete_smart(db: Session, user_id: str, item_id: int) -> str:
    """'ลบ 3' — งานกับรายการเงินนับ id คนละชุด เลขจึงซ้ำกันได้

    ถ้าซ้ำต้องถามก่อน ห้ามเดา: เคยเจอเคสผู้ใช้ตั้งใจลบรายจ่ายแต่บอทลบงานให้
    แล้วตอบว่า "ลบแล้ว" — รายจ่ายยังอยู่ในสรุป ส่วนงานหายไปเงียบๆ
    """
    task = db.query(Task).filter_by(id=item_id, user_id=user_id).first()
    money = db.query(Expense).filter_by(id=item_id, user_id=user_id).first()

    if task is not None and money is not None:
        return (
            f"เลข #{item_id} มีทั้งสองอย่างครับ จะลบอันไหน?\n"
            f"📋 งาน: {task.title}\n"
            f"{expense.cat_emoji(money.category)} เงิน: {money.title} "
            f"{expense.money(money.amount)} บาท\n\n"
            f"พิมพ์ \"ลบงาน {item_id}\" หรือ \"ลบรายจ่าย {item_id}\""
        )
    if money is not None:
        return _delete_expense_reply(db, user_id, item_id)
    return _delete_task(db, user_id, item_id)


def _try_expense_add(db: Session, user_id: str, text: str):
    """ตัวสุดท้ายของ strict pipeline — ถ้าไม่ใช่คำสั่งงานใดๆ เลย ลองอ่านเป็นเงิน"""
    parsed = expense.parse_expense(text)
    if not parsed:
        return None
    return _save_expense(db, user_id, parsed)

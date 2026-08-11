"""บันทึกรายรับ-รายจ่ายจากข้อความ LINE สั้นๆ เช่น "กาแฟ 60"

แยกจาก line_handler เพื่อไม่ให้ไฟล์นั้นบวมไปกว่านี้ — ที่นี่รวม
regex parser (ตัวหลัก), การเดาหมวด, และการสรุปยอด

parse_expense() ตั้งใจให้ "ขี้ระแวง": ถ้าไม่มั่นใจว่าเป็นเงินให้คืน None
แล้วปล่อยให้ pipeline งานเดิมจัดการต่อ ดีกว่าเผลอบันทึก "ประชุม 3 โมง" เป็นรายจ่าย
"""
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pytz
from sqlalchemy.orm import Session

from app.models import Expense
from app.parser import TZ, now_local

# ===== หมวดหมู่ =====

CATEGORY_EMOJI = {
    "อาหาร": "🍜",
    "เดินทาง": "🚌",
    "บิล/ที่พัก": "🏠",
    "ช้อปปิ้ง": "🛍️",
    "สุขภาพ": "💊",
    "บันเทิง": "🎮",
    "การเรียน": "📚",
    "รายรับ": "💰",
    "อื่นๆ": "📦",
}

# เรียงตามลำดับความเฉพาะเจาะจง — เจอคำไหนก่อนใช้หมวดนั้น
CATEGORY_KEYWORDS = (
    ("บิล/ที่พัก", ("ค่าไฟ", "ค่าน้ำ", "ค่าเน็ต", "ค่าห้อง", "ค่าเช่า", "ค่าโทรศัพท์",
                    "ค่าส่วนกลาง", "บิล", "ประกัน", "internet", "wifi", "ผ่อน")),
    ("เดินทาง", ("แท็กซี่", "taxi", "grab", "bolt", "bts", "mrt", "วิน", "มอเตอร์ไซค์",
                 "น้ำมัน", "ค่ารถ", "รถไฟ", "รถทัวร์", "เครื่องบิน", "ทางด่วน", "ที่จอดรถ",
                 "ตั๋ว", "เติมน้ำมัน", "ค่าเดินทาง")),
    ("สุขภาพ", ("ยา", "หมอ", "โรงพยาบาล", "คลินิก", "ฟิตเนส", "ยิม", "ทำฟัน", "วิตามิน",
                "ตรวจสุขภาพ", "แว่น")),
    ("การเรียน", ("หนังสือ", "ค่าเทอม", "คอร์ส", "เครื่องเขียน", "ปริ้น", "ถ่ายเอกสาร",
                  "สมุด", "ปากกา", "ติว")),
    ("บันเทิง", ("เกม", "หนัง", "netflix", "spotify", "youtube", "คอนเสิร์ต", "เที่ยว",
                 "บอร์ดเกม", "การ์ด", "steam")),
    ("อาหาร", ("ข้าว", "กาแฟ", "ชา", "น้ำ", "ขนม", "อาหาร", "กิน", "ก๋วยเตี๋ยว", "ส้มตำ",
               "หมูกระทะ", "ชาบู", "พิซซ่า", "ไก่", "เบียร์", "เซเว่น", "7-11", "ร้านอาหาร",
               "บุฟเฟ่ต์", "ชานม", "ลาเต้", "นม", "ผลไม้", "เค้ก", "ไอติม", "ไอศกรีม",
               "หมูปิ้ง", "ข้าวเหนียว", "โกโก้", "น้ำอัดลม", "มาม่า")),
    ("ช้อปปิ้ง", ("เสื้อ", "กางเกง", "รองเท้า", "ของใช้", "shopee", "lazada", "ซื้อของ",
                  "เครื่องสำอาง", "กระเป๋า", "สบู่", "ยาสีฟัน", "แชมพู", "ทิชชู่")),
)

INCOME_CATEGORY = "รายรับ"


def guess_category(title: str, kind: str = "expense") -> str:
    if kind == "income":
        return INCOME_CATEGORY
    low = title.lower()
    for category, words in CATEGORY_KEYWORDS:
        if any(w in low for w in words):
            return category
    return "อื่นๆ"


def cat_emoji(category: str) -> str:
    return CATEGORY_EMOJI.get(category, "📦")


# ===== Parser =====

# ตัวเลขจำนวนเงิน: 60 / 1,200 / 45.50
_AMOUNT = r"\d[\d,]*(?:\.\d{1,2})?"
_UNIT = r"(?:บาท|บ\.|฿|baht)"

_TAIL_RE = re.compile(rf"^(?P<title>.*?)\s*(?P<amt>{_AMOUNT})\s*(?P<unit>{_UNIT})?$", re.I)
_HEAD_RE = re.compile(rf"^(?P<amt>{_AMOUNT})\s*(?P<unit>{_UNIT})?\s+(?P<title>.+)$", re.I)

# นาฬิกาแบบชัดเจน (มี : หรือมีคำบอกเวลาติดตัวเลข) → ไม่ใช่เงินแน่นอน
_TIME_EXPR_RE = re.compile(
    r"\d{1,2}:\d{2}"
    r"|\d+\s*(?:โมง|ทุ่ม|นาฬิกา|น\.)"
    r"|ตี\s*\d|บ่าย\s*\d"
    r"|เที่ยงคืน|เที่ยงวัน|โมงเช้า|โมงเย็น"
)

# คำที่แปลว่า "นี่คืองาน ไม่ใช่เงิน"
_TASK_WORDS = ("เตือน", "ทุกวัน", "ทุกจันทร์", "ทุกอังคาร", "ทุกพุธ", "ทุกพฤหัส",
               "ทุกศุกร์", "ทุกเสาร์", "ทุกอาทิตย์", "ทุกเดือน", "ทุกสัปดาห์",
               "พรุ่งนี้", "มะรืน", "deadline", "กำหนดส่ง")

# ขึ้นต้นด้วยคำสั่งเดิมของบอท → ห้ามตีความเป็นเงิน
_COMMAND_PREFIXES = ("เพิ่ม", "ลบ", "เสร็จ", "ยกเลิก", "เลื่อน", "โน้ต", "หางาน", "ค้นหา",
                     "แก้", "ตั้ง", "งาน", "กิจวัตร", "ช่วยเหลือ", "สรุป", "รายจ่าย",
                     "รายรับ", "add", "done", "del", "delete", "search", "list", "help",
                     "note", "snooze", "task")

_INCOME_PREFIXES = ("ได้รับ", "รับเงิน", "เงินเข้า", "ได้เงิน", "ขายได้", "รับ")
_EXPENSE_PREFIXES = ("จ่ายค่า", "จ่าย", "ซื้อ", "เสียค่า", "เสีย", "ใช้ไปกับ", "ใช้ไป", "หมดไปกับ")

_DAY_OFFSETS = (("เมื่อวานนี้", -1), ("เมื่อวาน", -1), ("วันนี้", 0))


def _to_amount(raw: str) -> Optional[float]:
    try:
        value = float(raw.replace(",", ""))
    except ValueError:
        return None
    if value <= 0 or value > 10_000_000:
        return None
    return value


def _looks_like_clock(raw: str, has_unit: bool) -> bool:
    """'15.30' อาจเป็น 15:30 น. — ถ้าไม่มีหน่วยเงินกำกับให้ถือว่าเป็นเวลา"""
    if has_unit or "." not in raw:
        return False
    whole, _, frac = raw.partition(".")
    if len(frac) != 2:
        return False
    try:
        return 0 <= int(whole) <= 23 and 0 <= int(frac) <= 59
    except ValueError:
        return False


def parse_expense(text: str) -> Optional[Dict]:
    """แปลง "กาแฟ 60" → dict หรือคืน None ถ้าไม่มั่นใจว่าเป็นเรื่องเงิน

    คืน {"kind", "title", "amount", "category", "days_offset"}
    """
    original = (text or "").strip()
    if not original or len(original) > 120:
        return None

    low = original.lower()
    if any(low.startswith(p) for p in _COMMAND_PREFIXES):
        return None
    if any(w in low for w in _TASK_WORDS):
        return None
    if _TIME_EXPR_RE.search(original):
        return None
    if re.search(r"\d{1,2}/\d{1,2}", original):      # วันที่ 10/5 → เป็นงาน
        return None

    body = original
    kind = "expense"

    # +100 / -60 นำหน้า = ระบุชนิดชัดเจน
    sign_income = body.startswith("+")
    sign_expense = body.startswith("-")
    if sign_income or sign_expense:
        kind = "income" if sign_income else "expense"
        body = body[1:].strip()

    # วันที่แบบง่าย (วันนี้ / เมื่อวาน) — อย่างอื่นปล่อยให้ AI จัดการ
    days_offset = 0
    for word, offset in _DAY_OFFSETS:
        if word in body:
            days_offset = offset
            body = body.replace(word, " ").strip()
            break

    if not sign_income and not sign_expense:
        for prefix in _INCOME_PREFIXES:
            if body.startswith(prefix):
                kind = "income"
                body = body[len(prefix):].strip()
                break
        else:
            for prefix in _EXPENSE_PREFIXES:
                if body.startswith(prefix):
                    # "จ่ายค่าไฟ" ต้องเหลือ "ค่าไฟ" → ตัดเฉพาะ "จ่าย"
                    keep = "ค่า" if prefix in ("จ่ายค่า", "เสียค่า") else ""
                    body = (keep + body[len(prefix):]).strip()
                    break

    body = re.sub(r"\s+", " ", body).strip(" -—:")
    if not body:
        return None

    match = _TAIL_RE.match(body) or _HEAD_RE.match(body)
    if not match:
        return None

    raw_amount = match.group("amt")
    has_unit = bool(match.group("unit"))
    if _looks_like_clock(raw_amount, has_unit):
        return None

    amount = _to_amount(raw_amount)
    if amount is None:
        return None

    title = (match.group("title") or "").strip(" -—:฿")
    title = re.sub(r"\s+", " ", title)
    if not title or title.isdigit() or len(title) > 60:
        return None
    if not re.search(r"[ก-๙a-zA-Z]", title):
        return None

    return {
        "kind": kind,
        "title": title,
        "amount": amount,
        "category": guess_category(title, kind),
        "days_offset": days_offset,
    }


# ===== DB helpers =====

def _to_utc_naive(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = TZ.localize(dt)
    return dt.astimezone(pytz.utc).replace(tzinfo=None)


def _to_local(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    return dt.astimezone(TZ)


def add_expense(db: Session, user_id: str, title: str, amount: float,
                kind: str = "expense", category: Optional[str] = None,
                days_offset: int = 0, spent_at_local: Optional[datetime] = None,
                note: Optional[str] = None) -> Expense:
    when = spent_at_local or (now_local() + timedelta(days=days_offset))
    row = Expense(
        user_id=user_id,
        title=title[:200],
        amount=round(float(amount), 2),
        kind="income" if kind == "income" else "expense",
        category=(category or guess_category(title, kind))[:30],
        spent_at=_to_utc_naive(when),
        note=note[:300] if note else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def month_range_utc(year: int, month: int):
    """คืน (start_utc, end_utc) ของเดือนนั้นตามเวลาไทย"""
    start_local = TZ.localize(datetime(year, month, 1))
    if month == 12:
        end_local = TZ.localize(datetime(year + 1, 1, 1))
    else:
        end_local = TZ.localize(datetime(year, month + 1, 1))
    return (start_local.astimezone(pytz.utc).replace(tzinfo=None),
            end_local.astimezone(pytz.utc).replace(tzinfo=None))


def day_range_utc(date_local):
    start_local = TZ.localize(datetime(date_local.year, date_local.month, date_local.day))
    end_local = start_local + timedelta(days=1)
    return (start_local.astimezone(pytz.utc).replace(tzinfo=None),
            end_local.astimezone(pytz.utc).replace(tzinfo=None))


def _query_range(db: Session, user_id: str, start_utc, end_utc) -> List[Expense]:
    return (db.query(Expense)
            .filter(Expense.user_id == user_id,
                    Expense.spent_at >= start_utc,
                    Expense.spent_at < end_utc)
            .order_by(Expense.spent_at.asc(), Expense.id.asc())
            .all())


def list_day(db: Session, user_id: str, date_local) -> List[Expense]:
    start, end = day_range_utc(date_local)
    return _query_range(db, user_id, start, end)


def list_month(db: Session, user_id: str, year: int, month: int) -> List[Expense]:
    start, end = month_range_utc(year, month)
    return _query_range(db, user_id, start, end)


def month_total(db: Session, user_id: str, year: int, month: int, kind: str = "expense") -> float:
    return sum(e.amount for e in list_month(db, user_id, year, month) if e.kind == kind)


def delete_expense(db: Session, user_id: str, expense_id: int) -> Optional[Expense]:
    row = (db.query(Expense)
           .filter(Expense.id == expense_id, Expense.user_id == user_id)
           .first())
    if row is None:
        return None
    db.delete(row)
    db.commit()
    return row


# ===== Formatting =====

THAI_MONTHS_SHORT = ["", "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
                     "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]


def money(value: float) -> str:
    if abs(value - round(value)) < 0.005:
        return f"{value:,.0f}"
    return f"{value:,.2f}"


def format_entry_line(row: Expense) -> str:
    local = _to_local(row.spent_at)
    sign = "+" if row.kind == "income" else "-"
    return (f"{cat_emoji(row.category)} #{row.id} {row.title} "
            f"{sign}{money(row.amount)} ({local.strftime('%H:%M')})")


def format_added(db: Session, user_id: str, row: Expense) -> str:
    local = _to_local(row.spent_at)
    day_word = "วันนี้"
    today = now_local().date()
    if local.date() == today - timedelta(days=1):
        day_word = "เมื่อวาน"
    elif local.date() != today:
        day_word = local.strftime("%d/%m")

    spent = month_total(db, user_id, local.year, local.month, "expense")
    income = month_total(db, user_id, local.year, local.month, "income")

    head = "💰 บันทึกรายรับแล้ว" if row.kind == "income" else "💸 บันทึกรายจ่ายแล้ว"
    lines = [
        f"{head} #{row.id}",
        f"{cat_emoji(row.category)} {row.title} — {money(row.amount)} บาท ({row.category})",
        f"📅 {day_word} {local.strftime('%H:%M')}",
        "",
        f"เดือน{THAI_MONTHS_SHORT[local.month]} จ่ายไป {money(spent)} บาท",
    ]
    if income:
        lines.append(f"รับมา {money(income)} บาท → เหลือ {money(income - spent)} บาท")
    return "\n".join(lines)


def _bar(ratio: float, width: int = 10) -> str:
    filled = max(1, int(round(ratio * width))) if ratio > 0 else 0
    return "█" * filled + "░" * (width - filled)


def format_month_summary(db: Session, user_id: str, year: int, month: int) -> str:
    rows = list_month(db, user_id, year, month)
    label = f"{THAI_MONTHS_SHORT[month]} {(year + 543) % 100:02d}"   # พ.ศ. สองหลัก
    if not rows:
        return (f"📊 สรุปเดือน {label}\n\nยังไม่มีรายการเลยครับ\n"
                f"ลองพิมพ์ \"กาแฟ 60\" ดูได้เลย")

    spent = sum(r.amount for r in rows if r.kind == "expense")
    income = sum(r.amount for r in rows if r.kind == "income")

    by_cat: Dict[str, float] = {}
    for r in rows:
        if r.kind == "expense":
            by_cat[r.category] = by_cat.get(r.category, 0.0) + r.amount

    lines = [f"📊 สรุปเดือน {label}"]
    if income:
        lines.append(f"💰 รับ {money(income)}  💸 จ่าย {money(spent)}")
        balance = income - spent
        lines.append(f"{'✅' if balance >= 0 else '⚠️'} คงเหลือ {money(balance)} บาท")
    else:
        lines.append(f"💸 จ่ายไปทั้งหมด {money(spent)} บาท")

    if by_cat:
        lines.append("")
        for category, total in sorted(by_cat.items(), key=lambda kv: kv[1], reverse=True):
            pct = total / spent if spent else 0
            lines.append(f"{cat_emoji(category)} {category} {money(total)} "
                         f"({pct * 100:.0f}%)\n{_bar(pct)}")

    days = len({_to_local(r.spent_at).date() for r in rows if r.kind == "expense"})
    if days:
        lines.append("")
        lines.append(f"📈 เฉลี่ยวันละ {money(spent / days)} บาท ({days} วันที่มีรายการ)")
    return "\n".join(lines)


def format_day_list(db: Session, user_id: str, date_local, header: Optional[str] = None) -> str:
    rows = list_day(db, user_id, date_local)
    title = header or f"📅 {date_local.strftime('%d/%m')}"
    if not rows:
        return f"{title}\n\nยังไม่มีรายการครับ 👍"
    spent = sum(r.amount for r in rows if r.kind == "expense")
    income = sum(r.amount for r in rows if r.kind == "income")
    lines = [title, ""]
    lines += [format_entry_line(r) for r in rows]
    lines.append("")
    lines.append(f"รวมจ่าย {money(spent)} บาท" + (f" · รับ {money(income)} บาท" if income else ""))
    return "\n".join(lines)

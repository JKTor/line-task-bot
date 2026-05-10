"""Parse Thai task messages like:
    เพิ่ม ส่งรายงาน 10/5 18:00
    เพิ่ม ประชุมทีม พรุ่งนี้ 10:00
    เพิ่ม ทำการบ้าน วันนี้
    เพิ่ม อ่านหนังสือ                (no deadline)
"""
import re
from datetime import datetime, timedelta
from typing import Optional, Tuple

import pytz

TZ = pytz.timezone("Asia/Bangkok")

RELATIVE_DAYS = {
    "วันนี้": 0,
    "พรุ่งนี้": 1,
    "มะรืน": 2,
    "มะรืนนี้": 2,
}

# DD/MM or DD/MM/YY or DD/MM/YYYY
DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b")
# HH:MM or HH.MM
TIME_RE = re.compile(r"\b(\d{1,2})[:\.](\d{2})\b")


def now_local() -> datetime:
    return datetime.now(TZ)


def _to_utc_naive(dt: datetime) -> datetime:
    """Store timestamps as UTC-naive so SQLite/Postgres behave the same."""
    if dt.tzinfo is None:
        dt = TZ.localize(dt)
    return dt.astimezone(pytz.utc).replace(tzinfo=None)


def parse_task(text: str) -> Tuple[str, Optional[datetime]]:
    """Return (title, deadline_utc_naive). Deadline is None if not specified."""
    original = text.strip()
    title = original
    base_date: Optional[datetime] = None

    # 1) Relative day keywords
    for word, offset in RELATIVE_DAYS.items():
        if word in title:
            d = now_local() + timedelta(days=offset)
            base_date = d.replace(hour=23, minute=59, second=0, microsecond=0)
            title = title.replace(word, "").strip()
            break

    # 2) Explicit DD/MM date
    if base_date is None:
        m = DATE_RE.search(title)
        if m:
            day, month, year = m.group(1), m.group(2), m.group(3)
            today = now_local()
            y = today.year
            if year:
                y = int(year)
                if y < 100:
                    y += 2500 if y > 50 else 2000  # 67 -> 2567 BE? Most users will type AD
                    if y > 2400:
                        y -= 543  # convert BE -> AD
            try:
                candidate = TZ.localize(datetime(y, int(month), int(day), 23, 59))
                # If date already passed this year and no year specified, roll to next year
                if not year and candidate < today:
                    candidate = candidate.replace(year=candidate.year + 1)
                base_date = candidate
                title = (title[: m.start()] + title[m.end():]).strip()
            except ValueError:
                pass

    # 3) Time HH:MM (applies on top of the date if present, else today/tomorrow)
    tm = TIME_RE.search(title)
    if tm:
        hour, minute = int(tm.group(1)), int(tm.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            if base_date is None:
                base_date = now_local()
            base_date = base_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
            # If only time was given and it's already passed today, push to tomorrow
            if not (DATE_RE.search(original) or any(w in original for w in RELATIVE_DAYS)):
                if base_date < now_local():
                    base_date += timedelta(days=1)
            title = (title[: tm.start()] + title[tm.end():]).strip()

    # Tidy spaces
    title = re.sub(r"\s+", " ", title).strip(" -—:")

    deadline = _to_utc_naive(base_date) if base_date else None
    return title, deadline


def format_deadline(dt: Optional[datetime]) -> str:
    if dt is None:
        return "ไม่กำหนด"
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    local = dt.astimezone(TZ)
    today = now_local().date()
    if local.date() == today:
        prefix = "วันนี้"
    elif local.date() == today + timedelta(days=1):
        prefix = "พรุ่งนี้"
    else:
        prefix = local.strftime("%d/%m")
    return f"{prefix} {local.strftime('%H:%M')}"

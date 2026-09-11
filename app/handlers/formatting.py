"""แปลงข้อมูลเป็นข้อความที่ผู้ใช้เห็น + คำนวณวันเวลา

ไฟล์นี้ไม่แตะฐานข้อมูลเลย ทุกฟังก์ชันรับค่าเข้า-คืนค่าออกล้วน จึงเทสได้โดยไม่ต้องต่อ DB
"""
import calendar
from datetime import datetime, timedelta
from typing import List, Optional

import pytz

from app.handlers.constants import (
    _PRIORITY_EMOJI,
    _ROUTINE_DAY_NAMES,
    THAI_MONTHS,
    THAI_WEEKDAYS,
)
from app.models import Routine, Task
from app.parser import TZ, format_deadline, now_local

def _format_task_line(t: Task) -> str:
    mark = "✅" if t.done else _PRIORITY_EMOJI.get(getattr(t, "priority", "normal") or "normal", "⬜")
    recur = " 🔄" if t.recurring else ""
    note_mark = " 📝" if getattr(t, "note", None) else ""
    return f"{mark} #{t.id} {t.title}{recur}{note_mark}  ⏰ {format_deadline(t.deadline)}"


def _list_message(tasks: List[Task], header: str) -> str:
    if not tasks:
        return f"{header}\n(ไม่มีงาน 🎉)"
    return "\n".join([header] + [_format_task_line(t) for t in tasks])

def _format_routine_line(routine: Routine) -> str:
    return f"🔔 #{routine.id} {routine.title}  ⏰ {routine.time_hour:02d}:{routine.time_minute:02d}"

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

def _task_quick_reply(task_id: int) -> list:
    return [
        {"label": f"✅ เสร็จ #{task_id}", "text": f"เสร็จ {task_id}"},
        {"label": f"📅 เลื่อน #{task_id}", "text": f"เลื่อนงาน {task_id}"},
        {"label": f"🗑️ ลบ #{task_id}", "text": f"ลบงาน {task_id}"},
    ]

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

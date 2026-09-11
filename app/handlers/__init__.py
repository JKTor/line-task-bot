"""ตัวจัดการข้อความจาก LINE — เดิมเป็นไฟล์เดียว 1,133 บรรทัด (`app/line_handler.py`)

อ่านไล่ตามนี้ถ้าอยากรู้ว่าข้อความเดินทางยังไง:

    router.py       ทางเข้า — ตัดสินว่าส่งไปชั้นไหน  ← เริ่มที่นี่
      strict.py     ชั้น 1  จับ pattern (ส่วนใหญ่จบตรงนี้)
      ai_dispatch.py ชั้น 2 แปลงผลที่ AI ตีความเป็นการกระทำ

ทั้งสองชั้นเรียกโค้ดทำงานชุดเดียวกัน:

    tasks.py        งาน — เพิ่ม/ดู/ปิด/เลื่อน/ลบ
    routines.py     กิจวัตรประจำวัน
    money.py        รายรับ-รายจ่าย (+ _delete_smart จุดที่ id งานกับเงินชนกัน)
    clarify.py      สถานะรอคำตอบ + log ข้อความที่อ่านไม่ออก
    formatting.py   แปลงข้อมูลเป็นข้อความ + คำนวณวันเวลา (ไม่แตะ DB)
    constants.py    ข้อความคงที่

ทิศทางการพึ่งพาเป็นทางเดียวเสมอ: router → ชั้น 1/2 → tasks → routines → formatting
→ constants ไม่มี import วนกลับ
"""

from app.handlers.ai_dispatch import _dispatch_ai
from app.handlers.clarify import (
    _CANCEL_WORDS,
    _FRESH_COMMANDS,
    _PENDING_TTL_MIN,
    _clear_pending,
    _get_pending,
    _is_cancel,
    _log_unknown,
    _looks_like_fresh_command,
    _set_pending,
)
from app.handlers.constants import (
    HELP_TEXT,
    NUMBERED,
    THAI_MONTHS,
    THAI_WEEKDAYS,
    _PRIORITY_EMOJI,
    _PRIORITY_VALID,
    _ROUTINE_DAY_NAMES,
)
from app.handlers.formatting import (
    _ai_deadline_to_utc,
    _format_routine_days,
    _format_routine_line,
    _format_task_line,
    _label_for_date,
    _list_message,
    _next_recurring_deadline,
    _recurring_label,
    _routine_notify_str,
    _task_quick_reply,
)
from app.handlers.money import (
    _SUMMARY_WORDS,
    _TODAY_MONEY_WORDS,
    _YESTERDAY_MONEY_WORDS,
    _delete_expense_reply,
    _delete_smart,
    _expense_quick_reply,
    _local_date_or_none,
    _save_expense,
    _try_expense_add,
    _try_expense_command,
)
from app.handlers.router import _run_pipeline, handle_command
from app.handlers.routines import (
    _add_routine,
    _delete_all_routines,
    _delete_routine,
    _get_routines_for_date,
    _list_routines,
    _routine_matches_date,
    _update_routine,
)
from app.handlers.strict import (
    _LIST_QUESTION_WORDS,
    _THAI_TIME_WORDS,
    _looks_like_schedule_statement,
    _try_strict,
)
from app.handlers.tasks import (
    _add_note,
    _add_task,
    _cancel_recurring,
    _delete_all,
    _delete_task,
    _done_all,
    _format_add_beautiful,
    _get_tasks_for_date,
    _list_agenda_for_date,
    _list_all,
    _list_date,
    _list_overdue,
    _list_this_week,
    _list_today,
    _list_tomorrow,
    _list_urgent,
    _mark_done,
    _search_tasks,
    _set_priority,
    _snooze_task,
)

__all__ = ["handle_command", "HELP_TEXT"]

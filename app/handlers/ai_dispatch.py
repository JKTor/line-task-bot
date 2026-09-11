"""ชั้นที่ 2 — แปลงผลที่ AI ตีความแล้ว (dict) ให้กลายเป็นการกระทำจริง

AI ตอบมาแค่ว่า 'ผู้ใช้ต้องการอะไร' ส่วนการแตะฐานข้อมูลยังเป็นโค้ดชุดเดียวกับชั้น
pattern ทั้งหมด — AI จึงเปลี่ยนได้แค่การ *ตีความ* ไม่ได้เปลี่ยน *วิธีทำ*
"""
from sqlalchemy.orm import Session

from app import expense
from app.handlers.clarify import _log_unknown, _set_pending
from app.handlers.constants import HELP_TEXT
from app.handlers.formatting import (
    _ai_deadline_to_utc,
    _format_routine_days,
    _format_task_line,
    _routine_notify_str,
)
from app.handlers.money import (
    _delete_expense_reply,
    _delete_smart,
    _expense_quick_reply,
    _local_date_or_none,
)
from app.handlers.routines import (
    _add_routine,
    _delete_all_routines,
    _delete_routine,
    _list_routines,
    _update_routine,
)
from app.handlers.tasks import (
    _add_note,
    _add_task,
    _cancel_recurring,
    _delete_all,
    _done_all,
    _format_add_beautiful,
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
from app.parser import now_local

def _dispatch_ai(db: Session, user_id: str, intent: dict, allow_clarify: bool = True):
    action = intent.get("intent", "unknown")
    extra = intent.get("reply", "")

    if action == "clarify":
        tasks_raw = intent.get("tasks")
        tasks_in = tasks_raw if isinstance(tasks_raw, list) else []
        title = ""
        for t in tasks_in:
            if isinstance(t, dict) and (t.get("title") or "").strip():
                title = t["title"].strip()
                break
        if not title:
            return extra or "บอกชื่องานที่จะเตือนด้วยนะครับ"
        if not allow_clarify:
            # This is already the user's answer and it's still missing a time —
            # don't ask again (avoid loops). Just add the task without a deadline.
            saved = _add_task(db, user_id, title, None)
            return _format_add_beautiful(db, user_id, saved)
        _set_pending(db, user_id, title)
        return (
            (extra.strip() if extra else f"📅 อยากให้เตือน \"{title}\" วันไหน เวลาไหนดีครับ?")
            + "\n(ตอบเช่น 'พรุ่งนี้ 17:00' หรือพิมพ์ 'ยกเลิก')"
        )

    if action == "add":
        tasks_raw = intent.get("tasks")
        tasks_in = tasks_raw if isinstance(tasks_raw, list) else []
        if not tasks_in:
            return "ไม่เจอชื่องาน ลองพิมพ์ใหม่นะครับ"
        added = []
        for t in tasks_in:
            if not isinstance(t, dict):
                continue
            title = (t.get("title") or "").strip()
            if not title:
                continue
            deadline = _ai_deadline_to_utc(t.get("deadline"))
            recurring = t.get("recurring") or None
            priority = (t.get("priority") or "normal").strip().lower()
            note = t.get("note") or None
            saved = _add_task(db, user_id, title, deadline, recurring, priority, note)
            added.append(saved)
        if not added:
            return "ไม่เจอชื่องาน ลองพิมพ์ใหม่นะครับ"
        if len(added) == 1:
            return _format_add_beautiful(db, user_id, added[0])
        lines = ["✅ เพิ่มงานแล้ว"] + [_format_task_line(t) for t in added]
        return "\n".join(lines)

    if action == "list_today":
        return _list_today(db, user_id)

    if action == "list_tomorrow":
        return _list_tomorrow(db, user_id)

    if action == "list_week":
        return _list_this_week(db, user_id)

    if action == "list_overdue":
        return _list_overdue(db, user_id)

    if action == "list_date":
        date_str = intent.get("date") or ""
        return _list_date(db, user_id, str(date_str))

    if action == "list_urgent":
        return _list_urgent(db, user_id)

    if action == "list_all":
        return _list_all(db, user_id)

    if action == "search":
        kw = (intent.get("keyword") or "").strip()
        return _search_tasks(db, user_id, kw)

    if action == "add_note":
        tid = intent.get("task_id")
        note_text = (intent.get("note") or "").strip()
        if isinstance(tid, int) and note_text:
            return _add_note(db, user_id, tid, note_text)
        return "บอก id งานและโน้ตด้วยนะครับ เช่น 'เพิ่มโน้ต 3 ว่า ติดต่อต้น'"

    if action == "set_priority":
        tid = intent.get("task_id")
        p = (intent.get("priority") or "normal").strip().lower()
        if isinstance(tid, int):
            return _set_priority(db, user_id, tid, p)
        return "บอก id งานด้วยนะครับ เช่น 'ตั้ง priority งาน 3 เป็น urgent'"

    if action == "snooze":
        tid = intent.get("task_id")
        dl = intent.get("deadline")
        if isinstance(tid, int):
            return _snooze_task(db, user_id, tid, dl)
        return "บอก id งานและวันที่ใหม่ด้วยนะครับ เช่น 'เลื่อนงาน 3 เป็นพรุ่งนี้ 18:00'"

    if action == "update_routine":
        rid = intent.get("routine_id")
        r_raw = intent.get("routine")
        updates = r_raw if isinstance(r_raw, dict) else {}
        if isinstance(rid, int):
            return _update_routine(db, user_id, rid, updates)
        return "บอก id กิจวัตรด้วยนะครับ เช่น 'แก้กิจวัตร 1 เป็น 19:00'"

    if action == "done":
        tid = intent.get("task_id")
        if isinstance(tid, int):
            return _mark_done(db, user_id, tid)
        return "บอก id งานที่เสร็จด้วยนะครับ เช่น 'เสร็จ 3'"

    if action == "delete":
        tid = intent.get("task_id")
        if isinstance(tid, int):
            return _delete_smart(db, user_id, tid)
        return "บอก id งานที่จะลบด้วยนะครับ เช่น 'ลบ 3'"

    if action == "delete_all":
        return _delete_all(db, user_id)

    if action == "done_all":
        return _done_all(db, user_id)

    if action == "cancel_recurring":
        tid = intent.get("task_id")
        if isinstance(tid, int):
            return _cancel_recurring(db, user_id, tid)
        return "บอก id งานที่จะยกเลิกซ้ำด้วยนะครับ เช่น 'ยกเลิกซ้ำ 3'"

    if action == "add_routine":
        r_raw = intent.get("routine")
        r = r_raw if isinstance(r_raw, dict) else {}
        title = (r.get("title") or "").strip()
        if not title:
            return "ไม่เจอชื่อกิจวัตร ลองพิมพ์ใหม่นะครับ\nเช่น 'ออกกำลังกายทุกวัน 18.00'"
        time_str = (r.get("time") or "08:00").strip()
        try:
            parts = time_str.split(":")
            h, m = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
        except (ValueError, IndexError):
            h, m = 8, 0
        days = (r.get("days") or "daily").strip()
        if not days:
            days = "daily"
        try:
            advance = int(r.get("advance_minutes") or 30)
        except (TypeError, ValueError):
            advance = 30
        saved = _add_routine(db, user_id, title, h, m, days, advance)
        notify_str = _routine_notify_str(saved.time_hour, saved.time_minute, saved.advance_minutes)
        return (
            f"✅ เพิ่มกิจวัตรแล้ว!\n"
            f"🔔 #{saved.id} {saved.title} — {saved.time_hour:02d}:{saved.time_minute:02d} "
            f"{_format_routine_days(saved.days)}\n"
            f"⏰ จะแจ้งเตือนก่อน {saved.advance_minutes} นาที ({notify_str})"
        )

    if action == "list_routines":
        return _list_routines(db, user_id)

    if action == "delete_routine":
        rid = intent.get("routine_id")
        if isinstance(rid, int):
            return _delete_routine(db, user_id, rid)
        return "บอก id กิจวัตรที่จะลบด้วยนะครับ เช่น 'ลบกิจวัตร 1'"

    if action == "delete_all_routines":
        return _delete_all_routines(db, user_id)

    if action == "expense":
        raw = intent.get("expenses")
        rows = []
        for item in (raw if isinstance(raw, list) else []):
            if not isinstance(item, dict):
                continue
            title = (item.get("title") or "").strip()
            try:
                amount = float(item.get("amount"))
            except (TypeError, ValueError):
                continue
            if not title or amount <= 0:
                continue
            kind = "income" if item.get("kind") == "income" else "expense"
            rows.append(expense.add_expense(
                db, user_id, title=title, amount=amount, kind=kind,
                spent_at_local=_local_date_or_none(item.get("date")),
            ))
        if not rows:
            return "ไม่เจอจำนวนเงินครับ ลองพิมพ์แบบ 'กาแฟ 60' ดูนะ"
        if len(rows) == 1:
            return {"text": expense.format_added(db, user_id, rows[0]),
                    "quick_reply": _expense_quick_reply(rows[0].id)}
        total = sum(r.amount for r in rows if r.kind == "expense")
        lines = ["✅ บันทึกแล้ว %d รายการ" % len(rows), ""]
        lines += [expense.format_entry_line(r) for r in rows]
        lines.append("")
        lines.append(f"รวมจ่าย {expense.money(total)} บาท")
        return {"text": "\n".join(lines), "quick_reply": _expense_quick_reply(rows[-1].id)}

    if action == "expense_summary":
        month_str = intent.get("month")
        target = now_local()
        if isinstance(month_str, str) and len(month_str) >= 7:
            try:
                target = target.replace(year=int(month_str[:4]), month=int(month_str[5:7]), day=1)
            except ValueError:
                pass
        return expense.format_month_summary(db, user_id, target.year, target.month)

    if action == "expense_list":
        when = _local_date_or_none(intent.get("date")) or now_local()
        return expense.format_day_list(db, user_id, when.date(),
                                       f"📅 เงินวันที่ {when.strftime('%d/%m')}")

    if action == "expense_delete":
        eid = intent.get("expense_id")
        if isinstance(eid, int):
            return _delete_expense_reply(db, user_id, eid)
        return "บอก id ของรายการที่จะลบด้วยนะครับ เช่น 'ลบรายจ่าย 3'"

    if action == "help":
        return HELP_TEXT

    # Unknown intent — log for self-improvement review
    _log_unknown(db, user_id, intent.get("_original_text", ""), action)
    if extra:
        return f"{extra}\n\n{HELP_TEXT}"
    return HELP_TEXT

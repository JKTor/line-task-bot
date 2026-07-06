"""Unit tests for the pure Thai parsing helpers — no DB, no AI, no network.

Covers parse_task (date/time extraction) and the line_handler guards that decide
whether a message is a cancel / a fresh command / a schedule statement.

Run from repo root:
    python scripts/test_parser_th.py
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.parser import now_local, parse_task, TZ  # noqa: E402
from app import line_handler as lh  # noqa: E402

import pytz  # noqa: E402

_fail = []


def check(name, cond):
    mark = "✓" if cond else "✗"
    print(f"  {mark} {name}")
    if not cond:
        _fail.append(name)


def _local(dt_utc_naive):
    return pytz.utc.localize(dt_utc_naive).astimezone(TZ)


def test_parse_task():
    print("\nparse_task():")

    # relative day, no time -> tomorrow 23:59
    title, dl = parse_task("ส่งรายงาน พรุ่งนี้")
    check("พรุ่งนี้ -> title cleaned", title == "ส่งรายงาน")
    tmr = (now_local() + timedelta(days=1)).date()
    check("พรุ่งนี้ -> date is tomorrow", dl is not None and _local(dl).date() == tmr)
    check("พรุ่งนี้ -> default 23:59", dl is not None and _local(dl).strftime("%H:%M") == "23:59")

    # relative day + explicit time
    title, dl = parse_task("ประชุมทีม พรุ่งนี้ 10:00")
    check("พรุ่งนี้ 10:00 -> title", title == "ประชุมทีม")
    check("พรุ่งนี้ 10:00 -> time applied", dl is not None and _local(dl).strftime("%H:%M") == "10:00")

    # dotted time form HH.MM
    _, dl = parse_task("อ่านหนังสือ วันนี้ 18.30")
    check("18.30 dotted time parsed", dl is not None and _local(dl).strftime("%H:%M") == "18:30")

    # no deadline at all
    title, dl = parse_task("อ่านหนังสือ")
    check("no date -> deadline None", dl is None)
    check("no date -> title kept", title == "อ่านหนังสือ")

    # DD/MM explicit date
    title, dl = parse_task("จ่ายบิล 25/12 09:00")
    check("25/12 -> title cleaned", title == "จ่ายบิล")
    check("25/12 -> month/day", dl is not None and _local(dl).month == 12 and _local(dl).day == 25)


def test_cancel_guard():
    print("\n_is_cancel():")
    check("'ยกเลิก' cancels", lh._is_cancel("ยกเลิก"))
    check("'ยกเลิกงาน' cancels (startswith)", lh._is_cancel("ยกเลิกงาน"))
    check("'cancel' cancels", lh._is_cancel("Cancel"))
    # regression: the substring 'เลิก' must NOT cancel a real answer
    check("'หลังเลิกงาน 6 โมง' is NOT cancel", not lh._is_cancel("หลังเลิกงาน 6 โมง"))
    check("'เลิกเรียน 17:00' is NOT cancel", not lh._is_cancel("เลิกเรียน 17:00"))
    check("'พรุ่งนี้ 17:00' is NOT cancel", not lh._is_cancel("พรุ่งนี้ 17:00"))


def test_fresh_command_guard():
    print("\n_looks_like_fresh_command():")
    check("'งานวันนี้' is fresh command", lh._looks_like_fresh_command("งานวันนี้"))
    check("'ช่วยเหลือ' is fresh command", lh._looks_like_fresh_command("ช่วยเหลือ"))
    check("'help' is fresh command", lh._looks_like_fresh_command("HELP"))
    # a date answer must NOT be mistaken for a command
    check("'พรุ่งนี้ 17:00' is NOT a command", not lh._looks_like_fresh_command("พรุ่งนี้ 17:00"))
    check("'พรุ่งนี้' alone is NOT in the set", not lh._looks_like_fresh_command("พรุ่งนี้"))


def test_schedule_statement():
    print("\n_looks_like_schedule_statement():")

    def st(text):
        return lh._looks_like_schedule_statement(text, text.lower())

    check("'พรุ่งนี้ ประชุม 10 โมง' -> schedule stmt", st("พรุ่งนี้ ประชุม 10 โมง"))
    check("'วันนี้ ส่งงาน 18:00' -> schedule stmt", st("วันนี้ ส่งงาน 18:00"))
    # a plain list question must NOT be treated as a schedule statement
    check("'พรุ่งนี้มีอะไรบ้าง' -> NOT schedule stmt", not st("พรุ่งนี้มีอะไรบ้าง"))
    check("'งานวันนี้' -> NOT schedule stmt", not st("งานวันนี้"))


def main():
    test_parse_task()
    test_cancel_guard()
    test_fresh_command_guard()
    test_schedule_statement()
    print("\n" + ("ALL PASS ✅" if not _fail else f"FAILURES ✗ ({len(_fail)}): " + ", ".join(_fail)))
    return 0 if not _fail else 1


if __name__ == "__main__":
    raise SystemExit(main())

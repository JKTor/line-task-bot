"""Verify maybe_send_weekly() fires exactly once per week on Monday >= 08:00.

No LINE calls — _push is stubbed to just count. Uses a throwaway SQLite DB.
Run from repo root:
    python scripts/test_weekly_guard.py
"""
import os
import sys
from datetime import datetime

_DB_FILE = "_test_weekly.db"
os.environ["DATABASE_URL"] = f"sqlite:///./{_DB_FILE}"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if os.path.exists(_DB_FILE):
    os.remove(_DB_FILE)

from app.database import SessionLocal, engine, init_db  # noqa: E402
from app.models import Task, User  # noqa: E402
from app import scheduler  # noqa: E402
from app.parser import TZ  # noqa: E402

_fail = []
_pushes = []


def check(name, cond):
    print(f"  {'✓' if cond else '✗'} {name}")
    if not cond:
        _fail.append(name)


def _at(y, mo, d, h, mi=0):
    """Return a fixed Bangkok-aware 'now' and install it on the scheduler."""
    fixed = TZ.localize(datetime(y, mo, d, h, mi))
    scheduler.now_local = lambda: fixed


def main():
    init_db(retries=1)
    # one user with a task so weekly_summary has someone to notify
    db = SessionLocal()
    db.add(User(line_user_id="U1", display_name="U"))
    db.add(Task(user_id="U1", title="งานทดสอบ"))
    db.commit()
    db.close()

    # stub the LINE push so nothing leaves the process
    scheduler._push = lambda token, uid, text: _pushes.append((uid, text))

    TOKEN = "fake"

    # 2026-07-06 is a Monday.
    print("\nMonday before 08:00 -> not due:")
    _at(2026, 7, 6, 7, 30)
    check("07:30 sends nothing", scheduler.maybe_send_weekly(TOKEN) == 0)

    print("\nMonday 08:00 -> sends once:")
    _at(2026, 7, 6, 8, 0)
    n1 = scheduler.maybe_send_weekly(TOKEN)
    check("first Monday call sends (>0)", n1 > 0)

    print("\nMonday 08:05 same week -> deduped:")
    _at(2026, 7, 6, 8, 5)
    check("second call same week sends 0", scheduler.maybe_send_weekly(TOKEN) == 0)

    print("\nTuesday -> not due:")
    _at(2026, 7, 7, 9, 0)
    check("Tuesday sends 0", scheduler.maybe_send_weekly(TOKEN) == 0)

    print("\nNext Monday -> sends again:")
    _at(2026, 7, 13, 8, 0)  # following Monday
    check("next week sends again (>0)", scheduler.maybe_send_weekly(TOKEN) > 0)

    check("exactly 2 weekly pushes total", len(_pushes) == 2)

    print("\n" + ("ALL PASS ✅" if not _fail else f"FAILURES ✗: {', '.join(_fail)}"))
    return 0 if not _fail else 1


if __name__ == "__main__":
    code = 1
    try:
        code = main()
    finally:
        engine.dispose()
        try:
            os.remove(_DB_FILE)
        except OSError:
            pass
    raise SystemExit(code)

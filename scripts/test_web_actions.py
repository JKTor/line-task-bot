"""Exercise the /dashboard web actions (done/delete task, delete routine) directly.

No HTTP server needed — calls the route functions with a real signed session
token against a throwaway SQLite DB. Verifies the happy path AND that ownership
is enforced (user A cannot touch user B's rows).

Run from repo root:
    python scripts/test_web_actions.py
"""
import os
import sys

_DB_FILE = "_test_web.db"
os.environ["DATABASE_URL"] = f"sqlite:///./{_DB_FILE}"
os.environ.setdefault("JWT_SECRET", "test-secret-for-web-actions")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if os.path.exists(_DB_FILE):
    os.remove(_DB_FILE)

from app.database import SessionLocal, engine, init_db  # noqa: E402
from app.models import Routine, Task, User  # noqa: E402
from app import main as web  # noqa: E402
from app.auth import create_session_token  # noqa: E402

_fail = []


def check(name, cond):
    print(f"  {'✓' if cond else '✗'} {name}")
    if not cond:
        _fail.append(name)


def main():
    init_db(retries=1)
    db = SessionLocal()

    # two users, each owning one task; user A also owns a routine
    db.add_all([
        User(line_user_id="U_A", display_name="A"),
        User(line_user_id="U_B", display_name="B"),
    ])
    ta = Task(user_id="U_A", title="งาน A")
    tb = Task(user_id="U_B", title="งาน B")
    ra = Routine(user_id="U_A", title="ออกกำลังกาย", time_hour=18, time_minute=0, days="daily")
    db.add_all([ta, tb, ra])
    db.commit()
    a_task, b_task, a_routine = ta.id, tb.id, ra.id

    token_a = create_session_token("U_A")

    print("\nweb_task_done():")
    web.web_task_done(a_task, filter="all", session_token=token_a, db=db)
    db.expire_all()
    check("A can mark own task done", db.get(Task, a_task).done is True)

    print("\nownership on done:")
    web.web_task_done(b_task, filter="all", session_token=token_a, db=db)
    db.expire_all()
    check("A cannot mark B's task done", db.get(Task, b_task).done is False)

    print("\nweb_task_delete():")
    web.web_task_delete(b_task, filter="all", session_token=token_a, db=db)
    check("A cannot delete B's task", db.get(Task, b_task) is not None)
    web.web_task_delete(a_task, filter="all", session_token=token_a, db=db)
    check("A can delete own task", db.get(Task, a_task) is None)

    print("\nweb_routine_delete():")
    web.web_routine_delete(a_routine, filter="today", session_token=token_a, db=db)
    check("A can delete own routine", db.get(Routine, a_routine) is None)

    print("\nunauthenticated:")
    r = web.web_task_delete(b_task, filter="all", session_token=None, db=db)
    check("no session -> redirect to /auth/line", getattr(r, "status_code", None) in (302, 307)
          and r.headers.get("location") == "/auth/line")
    check("B's task still intact", db.get(Task, b_task) is not None)

    db.close()
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

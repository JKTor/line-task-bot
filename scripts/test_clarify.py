"""Simulate the clarify flow end-to-end against a throwaway SQLite DB.

Mocks ai_parser so it's deterministic (no real Groq call). Run from repo root:
    python scripts/test_clarify.py
"""
import os
import sys

_DB_FILE = "_test_clarify.db"
os.environ["DATABASE_URL"] = f"sqlite:///./{_DB_FILE}"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# start from a clean DB so a stale row from a previous run can't leak in
if os.path.exists(_DB_FILE):
    os.remove(_DB_FILE)

from app.database import SessionLocal, engine, init_db
from app import ai_parser, line_handler

USER = "U_test_clarify"

# Scripted AI responses keyed by a substring of the incoming text.
_SCRIPT = {}


def _fake_parse(text: str):
    for needle, resp in _SCRIPT.items():
        if needle in text:
            return dict(resp)
    return {"intent": "unknown"}


def run(db, text):
    reply = line_handler.handle_command(db, USER, text)
    shown = reply["text"] if isinstance(reply, dict) else reply
    print(f"\n>>> USER: {text}\n<<< BOT : {shown.splitlines()[0]}")
    return reply


def main() -> int:
    init_db(retries=1)
    ai_parser.is_enabled = lambda: True
    ai_parser.parse = _fake_parse

    db = SessionLocal()
    ok = True

    # 1) reminder with no date -> AI says clarify -> bot asks + stores pending
    _SCRIPT.clear()
    _SCRIPT["ส่งเอกสาร"] = {"intent": "clarify", "tasks": [{"title": "ส่งเอกสาร"}],
                            "reply": "📅 อยากให้เตือน 'ส่งเอกสาร' วันไหน เวลาไหนดีครับ?"}
    r1 = run(db, "เตือนส่งเอกสาร")
    pend = line_handler._get_pending(db, USER)
    if pend is None or "วันไหน" not in (r1 if isinstance(r1, str) else r1["text"]):
        print("  ✗ expected a clarify question + stored pending"); ok = False
    else:
        print(f"  ✓ pending stored: title={pend.title!r}")

    # 2) user answers with a date -> merged + added with a real deadline
    _SCRIPT.clear()
    _SCRIPT["ส่งเอกสาร"] = {"intent": "add",
                            "tasks": [{"title": "ส่งเอกสาร", "deadline": "2026-07-07 17:00"}]}
    r2 = run(db, "พรุ่งนี้ 17:00")
    from app.models import Task
    t = db.query(Task).filter_by(user_id=USER, title="ส่งเอกสาร").first()
    if t is None or t.deadline is None:
        print("  ✗ expected task added WITH a deadline"); ok = False
    else:
        print(f"  ✓ task #{t.id} added, deadline(utc)={t.deadline}")
    if line_handler._get_pending(db, USER) is not None:
        print("  ✗ pending should be cleared after answer"); ok = False
    else:
        print("  ✓ pending cleared")

    # 3) clarify then cancel -> no task, pending cleared
    _SCRIPT.clear()
    _SCRIPT["จ่ายบิล"] = {"intent": "clarify", "tasks": [{"title": "จ่ายบิล"}], "reply": "ถามวัน"}
    run(db, "อย่าลืมจ่ายบิล")
    before = db.query(Task).filter_by(user_id=USER).count()
    run(db, "ยกเลิก")
    after = db.query(Task).filter_by(user_id=USER).count()
    if after != before or line_handler._get_pending(db, USER) is not None:
        print("  ✗ cancel should add nothing and clear pending"); ok = False
    else:
        print("  ✓ cancel added nothing, pending cleared")

    # 4) plain note (deadline intentionally null) must NOT trigger clarify
    _SCRIPT.clear()
    _SCRIPT["ซื้อยา"] = {"intent": "add",
                         "tasks": [{"title": "ซื้อยา", "deadline": None, "priority": "low"}]}
    run(db, "จดไว้ ซื้อยา ไม่รีบ")
    if line_handler._get_pending(db, USER) is not None:
        print("  ✗ note-style add must not create a pending clarify"); ok = False
    else:
        print("  ✓ note added, no clarify")

    # 5) answer still missing a time -> add anyway, no re-loop
    _SCRIPT.clear()
    _SCRIPT["โทรหาแม่"] = {"intent": "clarify", "tasks": [{"title": "โทรหาแม่"}], "reply": "ถามวัน"}
    run(db, "เตือนโทรหาแม่")
    _SCRIPT.clear()
    _SCRIPT["โทรหาแม่"] = {"intent": "clarify", "tasks": [{"title": "โทรหาแม่"}], "reply": "ถามวันอีก"}
    run(db, "ก็ไม่รู้สิ")
    # contract: no re-loop, and the task is saved (title may carry the extra words
    # when the answer wasn't a real date — acceptable degenerate case)
    added = db.query(Task).filter(Task.user_id == USER,
                                  Task.title.like("โทรหาแม่%")).first()
    if line_handler._get_pending(db, USER) is not None:
        print("  ✗ must not loop into another pending clarify"); ok = False
    elif added is None:
        print("  ✗ should have added the task anyway"); ok = False
    else:
        print(f"  ✓ second miss added task #{added.id} ({added.title!r}), no loop")

    db.close()
    print("\n" + ("ALL PASS ✅" if ok else "FAILURES ✗"))
    return 0 if ok else 1


if __name__ == "__main__":
    code = 1
    try:
        code = main()
    finally:
        engine.dispose()  # release the sqlite file handle before deleting
        try:
            os.remove(_DB_FILE)
        except OSError:
            pass
    raise SystemExit(code)

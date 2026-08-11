"""Smoke-test every HTML page: does it actually render?

Catches the class of bug where a template call still uses the old
TemplateResponse("name.html", {...}) form, which starlette 1.0 removed.
Renders each page for real through TestClient against a throwaway SQLite DB.

Run from repo root:
    python scripts/test_web_pages.py
"""
import os
import sys

_DB_FILE = "_test_pages.db"
os.environ["DATABASE_URL"] = f"sqlite:///./{_DB_FILE}"
os.environ.setdefault("JWT_SECRET", "test-secret-for-pages")
os.environ["ADMIN_SECRET"] = "test-admin-secret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if os.path.exists(_DB_FILE):
    os.remove(_DB_FILE)

from fastapi.testclient import TestClient  # noqa: E402

from app import expense  # noqa: E402
from app.auth import create_session_token  # noqa: E402
from app.database import SessionLocal, init_db  # noqa: E402
from app.models import Routine, Task, User  # noqa: E402
from app import main as web  # noqa: E402

_fail = []
USER = "U_pages_test"
ADMIN = "test-admin-secret"


def check(name, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {name}{'' if cond else '  ' + detail}")
    if not cond:
        _fail.append(name)


def seed():
    init_db(retries=1)
    db = SessionLocal()
    try:
        db.add(User(line_user_id=USER, display_name="ทดสอบ"))
        db.add(Task(user_id=USER, title="ส่งรายงาน"))
        db.add(Routine(user_id=USER, title="ออกกำลังกาย", time_hour=18, time_minute=0))
        db.commit()
        expense.add_expense(db, USER, "กาแฟ", 60)
        expense.add_expense(db, USER, "เงินเดือน", 15000, kind="income")
    finally:
        db.close()


def main():
    seed()
    token = create_session_token(USER)
    client = TestClient(web.app, cookies={"session_token": token})

    print("\n[pages] ทุกหน้าต้อง render ได้ (status 200)")
    # "/" redirects ไป /dashboard ถ้าล็อกอินอยู่ → เทสด้วย client ที่ไม่ล็อกอิน
    landing = TestClient(web.app).get("/", follow_redirects=False)
    check("หน้าแรก (/)", landing.status_code == 200 and "<html" in landing.text.lower(),
          f"status={landing.status_code}")

    pages = [
        ("ตั้งค่า", "/dashboard"),
        ("งานทั้งหมด", "/dashboard/tasks"),
        ("งานวันนี้ (filter)", "/dashboard/tasks?filter=today"),
        ("เงิน", "/dashboard/expenses"),
        ("เงินเดือนก่อน", "/dashboard/expenses?month=2026-01"),
        ("admin", f"/admin?secret={ADMIN}"),
        ("admin unknown", f"/admin/unknown?secret={ADMIN}"),
    ]
    for label, url in pages:
        try:
            resp = client.get(url, follow_redirects=False)
            ok = resp.status_code == 200 and "<html" in resp.text.lower()
            check(f"{label} ({url})", ok, f"status={resp.status_code}")
        except Exception as exc:  # template ที่เรียกผิดรูปแบบจะระเบิดตรงนี้
            check(f"{label} ({url})", False, f"{type(exc).__name__}: {exc}")

    print("\n[pages] เนื้อหาสำคัญอยู่ครบ")
    tasks_html = client.get("/dashboard/tasks").text
    check("หน้างานเห็นงานที่ seed", "ส่งรายงาน" in tasks_html)
    check("หน้างานมีลิงก์ไปหน้าเงิน", "/dashboard/expenses" in tasks_html)
    money_html = client.get("/dashboard/expenses").text
    check("หน้าเงินเห็นกาแฟ", "กาแฟ" in money_html)
    check("หน้าเงินเห็นรายรับ", "15,000" in money_html)

    print("\n[pages] หน้าเว็บที่ต้องกันคนนอก")
    anon = TestClient(web.app)
    for label, url in [("ตั้งค่า", "/dashboard"), ("งาน", "/dashboard/tasks"),
                       ("เงิน", "/dashboard/expenses")]:
        resp = anon.get(url, follow_redirects=False)
        check(f"{label} ไม่ล็อกอิน → redirect", resp.status_code in (302, 307))
    resp = anon.get("/admin?secret=wrong", follow_redirects=False)
    check("admin secret ผิด → ไม่ผ่าน", resp.status_code != 200)

    print()
    if _fail:
        print(f"❌ ไม่ผ่าน {len(_fail)} เคส")
        sys.exit(1)
    print("✅ ผ่านทั้งหมด")


if __name__ == "__main__":
    main()

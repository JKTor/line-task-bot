"""Tests for the money (รายรับ-รายจ่าย) feature — no AI, no network.

Two halves:
  1. parse_expense() — pure regex. The important half: it must NOT swallow
     task messages like "ประชุม 3 โมง" or "ลบ 2".
  2. handle_command() end-to-end against a throwaway SQLite DB (AI disabled),
     so the strict pipeline ordering is exercised for real.

Run from repo root:
    python scripts/test_expense.py
"""
import os
import sys

_DB_FILE = "_test_expense.db"
os.environ["DATABASE_URL"] = f"sqlite:///./{_DB_FILE}"
os.environ.pop("GROQ_API_KEY", None)      # ปิด AI: ทดสอบเฉพาะ strict pipeline
os.environ.pop("GEMINI_API_KEY", None)
os.environ.setdefault("JWT_SECRET", "test-secret-for-expense")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if os.path.exists(_DB_FILE):
    os.remove(_DB_FILE)

from app import expense  # noqa: E402
from app import line_handler as lh  # noqa: E402
from app.database import SessionLocal, init_db  # noqa: E402
from app.models import Expense, Task  # noqa: E402
from app.parser import now_local  # noqa: E402

_fail = []
USER = "U_money_test"


def check(name, cond):
    print(f"  {'✓' if cond else '✗'} {name}")
    if not cond:
        _fail.append(name)


def reply_text(result):
    return result["text"] if isinstance(result, dict) else result


# ── 1. parser ────────────────────────────────────────────────────────────────

def test_parses_money():
    print("\n[parse] ข้อความที่ต้องอ่านเป็นเงิน")
    cases = [
        ("กาแฟ 60", "กาแฟ", 60, "expense", "อาหาร"),
        ("ข้าวเที่ยง 45", "ข้าวเที่ยง", 45, "expense", "อาหาร"),
        ("กาแฟ 60 บาท", "กาแฟ", 60, "expense", "อาหาร"),
        ("กาแฟ60", "กาแฟ", 60, "expense", "อาหาร"),
        ("ค่าไฟ 1,250", "ค่าไฟ", 1250, "expense", "บิล/ที่พัก"),
        ("จ่ายค่าไฟ 800", "ค่าไฟ", 800, "expense", "บิล/ที่พัก"),
        ("ซื้อรองเท้า 1200", "รองเท้า", 1200, "expense", "ช้อปปิ้ง"),
        ("แท็กซี่ 85.50", "แท็กซี่", 85.5, "expense", "เดินทาง"),
        ("-60 กาแฟ", "กาแฟ", 60, "expense", "อาหาร"),
        ("รับ เงินเดือน 15000", "เงินเดือน", 15000, "income", "รายรับ"),
        ("+500 ค่าขนม", "ค่าขนม", 500, "income", "รายรับ"),
        ("ได้เงิน ขายของ 300", "ขายของ", 300, "income", "รายรับ"),
    ]
    for text, title, amount, kind, category in cases:
        got = expense.parse_expense(text)
        ok = (got is not None and got["title"] == title
              and abs(got["amount"] - amount) < 0.001
              and got["kind"] == kind and got["category"] == category)
        check(f"{text!r} → {title} {amount} {kind}/{category}"
              + ("" if ok else f"  (ได้ {got})"), ok)


def test_rejects_tasks():
    print("\n[parse] ข้อความที่ห้ามอ่านเป็นเงิน (ต้องคืน None)")
    for text in [
        "ประชุม 3 โมง",
        "ประชุมทีม 15:30",
        "ประชุม 15.30",
        "เสร็จ 3",
        "ลบ 2",
        "เพิ่ม ส่งรายงาน 18:00",
        "งาน 3 เสร็จแล้ว",
        "เตือนจ่ายค่าไฟ 800",
        "พรุ่งนี้จ่ายค่าเน็ต 599",
        "ส่งการบ้านทุกวัน 20:00",
        "กินยา 2 ทุ่ม",
        "ส่งรายงาน 10/5",
        "วันนี้",
        "สรุป",
        "ช่วยเหลือ",
        "60",
        "",
    ]:
        got = expense.parse_expense(text)
        check(f"{text!r} → None" + ("" if got is None else f"  (ได้ {got})"), got is None)


def test_day_offset():
    print("\n[parse] วันที่แบบง่าย")
    got = expense.parse_expense("เมื่อวาน กาแฟ 60")
    check("'เมื่อวาน กาแฟ 60' → offset -1", got is not None and got["days_offset"] == -1)
    got = expense.parse_expense("วันนี้ ข้าว 50")
    check("'วันนี้ ข้าว 50' → offset 0", got is not None and got["days_offset"] == 0)


# ── 2. end-to-end ผ่าน handle_command ────────────────────────────────────────

def test_flow(db):
    print("\n[flow] บันทึก → สรุป → ลบ")

    res = lh.handle_command(db, USER, "กาแฟ 60")
    text = reply_text(res)
    rows = db.query(Expense).filter(Expense.user_id == USER).all()
    check("'กาแฟ 60' บันทึกลง DB 1 แถว", len(rows) == 1 and rows[0].amount == 60)
    check("ตอบกลับบอกว่าบันทึกรายจ่าย", "บันทึกรายจ่าย" in text)
    check("มี quick reply ปุ่มลบ", isinstance(res, dict) and len(res["quick_reply"]) == 3)
    check("ไม่ได้ถูกบันทึกเป็นงาน", db.query(Task).filter(Task.user_id == USER).count() == 0)

    lh.handle_command(db, USER, "ค่าไฟ 800")
    lh.handle_command(db, USER, "รับ เงินเดือน 15000")

    summary = reply_text(lh.handle_command(db, USER, "สรุป"))
    check("สรุปมียอดจ่ายรวม 860", "860" in summary)
    check("สรุปมียอดรับ 15,000", "15,000" in summary)
    check("สรุปมีคงเหลือ 14,140", "14,140" in summary)
    check("สรุปแยกหมวดอาหาร", "อาหาร" in summary and "บิล/ที่พัก" in summary)

    today = reply_text(lh.handle_command(db, USER, "รายจ่ายวันนี้"))
    check("รายการวันนี้เห็นกาแฟ", "กาแฟ" in today)
    check("รายการวันนี้รวมยอด 860", "860" in today)

    first_id = rows[0].id
    deleted = reply_text(lh.handle_command(db, USER, f"ลบรายจ่าย {first_id}"))
    check("ลบรายจ่ายได้", "ลบแล้ว" in deleted)
    check("เหลือ 2 แถวใน DB",
          db.query(Expense).filter(Expense.user_id == USER).count() == 2)

    check("ลบ id ที่ไม่มี → บอกไม่เจอ",
          "ไม่เจอ" in reply_text(lh.handle_command(db, USER, "ลบรายจ่าย 9999")))


def test_task_still_works(db):
    print("\n[flow] คำสั่งงานเดิมต้องไม่พัง")
    res = lh.handle_command(db, USER, "เพิ่ม ส่งรายงาน 18:00")
    check("เพิ่มงานยังได้", db.query(Task).filter(Task.user_id == USER).count() == 1)
    task = db.query(Task).filter(Task.user_id == USER).first()
    check("ชื่องานถูก", task.title == "ส่งรายงาน")

    done = reply_text(lh.handle_command(db, USER, f"เสร็จ {task.id}"))
    check("mark เสร็จยังได้", "เสร็จ" in done)

    check("'วันนี้' ยังเป็นคำสั่งดูงาน",
          "งาน" in reply_text(lh.handle_command(db, USER, "วันนี้")))
    check("'ช่วยเหลือ' ยังเป็น help",
          "คำสั่งที่ใช้ได้" in reply_text(lh.handle_command(db, USER, "ช่วยเหลือ")))


def test_ownership(db):
    print("\n[flow] ความปลอดภัย: ลบข้ามคนไม่ได้")
    other = expense.add_expense(db, "U_someone_else", "ของคนอื่น", 99)
    res = reply_text(lh.handle_command(db, USER, f"ลบรายจ่าย {other.id}"))
    check("ลบรายการคนอื่นไม่ได้", "ไม่เจอ" in res)
    check("แถวคนอื่นยังอยู่",
          db.query(Expense).filter(Expense.id == other.id).first() is not None)


def test_id_collision(db):
    """งานกับรายการเงินนับ id คนละชุด — 'ลบ 3' เคยลบงานทิ้งทั้งที่ผู้ใช้ตั้งใจลบรายจ่าย"""
    print("\n[flow] id ชนกันระหว่างงานกับเงิน")
    u = "U_collision"
    # จองเลขที่ยังว่างทั้งสองตาราง แล้วยัดให้งานกับรายจ่ายใช้เลขเดียวกัน
    free_id = max(
        db.query(Task).count() + db.query(Expense).count() + 100,
        (db.query(Task).order_by(Task.id.desc()).first().id if db.query(Task).count() else 0) + 100,
    )
    task = Task(id=free_id, user_id=u, title="งานชนเลข")
    same = Expense(id=free_id, user_id=u, title="กาแฟชนเลข", amount=60,
                   kind="expense", category="อาหาร",
                   spent_at=expense._to_utc_naive(now_local()))
    db.add_all([task, same])
    db.commit()

    res = reply_text(lh.handle_command(db, u, f"ลบ {task.id}"))
    check("'ลบ <id>' ที่ชนกัน → ถามก่อน", "จะลบอันไหน" in res)
    check("ยังไม่ลบงาน", db.query(Task).filter_by(id=task.id).first() is not None)
    check("ยังไม่ลบรายจ่าย", db.query(Expense).filter_by(id=same.id).first() is not None)

    res = reply_text(lh.handle_command(db, u, f"ลบงาน {task.id}"))
    check("'ลบงาน <id>' ลบเฉพาะงาน", "ลบงานแล้ว" in res)
    check("งานถูกลบ", db.query(Task).filter_by(id=task.id).first() is None)
    check("รายจ่ายยังอยู่", db.query(Expense).filter_by(id=same.id).first() is not None)

    summary = reply_text(lh.handle_command(db, u, "สรุป"))
    check("สรุปยังนับรายจ่าย 60 อยู่ (ยังไม่ได้ลบ)", "60" in summary)

    # ตอนนี้เหลือแค่รายจ่ายที่เลขนี้ → 'ลบ <id>' ต้องเข้าใจว่าหมายถึงเงิน
    res = reply_text(lh.handle_command(db, u, f"ลบ {same.id}"))
    check("'ลบ <id>' ที่มีแต่รายการเงิน → ลบเงินให้เลย", "ลบแล้ว" in res)
    check("รายจ่ายถูกลบจริง", db.query(Expense).filter_by(id=same.id).first() is None)

    # ลบหมดแล้ว → ต้องได้ข้อความ "ยังไม่มีรายการ"
    # (เช็คว่าไม่มีเลข 60 ไม่ได้ เพราะข้อความตัวอย่างในนั้นมีคำว่า "กาแฟ 60")
    summary = reply_text(lh.handle_command(db, u, "สรุป"))
    check("สรุปไม่รวมรายการที่ลบแล้ว", "ยังไม่มีรายการ" in summary)


def test_web(db):
    print("\n[web] หน้า /dashboard/expenses")
    from app import main as web
    from app.auth import create_session_token
    from app.models import User

    if db.query(User).filter_by(line_user_id=USER).first() is None:
        db.add(User(line_user_id=USER, display_name="ทดสอบ"))
        db.commit()
    token = create_session_token(USER)

    from fastapi.testclient import TestClient
    client = TestClient(web.app, cookies={"session_token": token})

    resp = client.get("/dashboard/expenses")
    html = resp.text
    check("หน้าโหลดได้ (status 200)", resp.status_code == 200)
    check("เห็นรายการค่าไฟ", "ค่าไฟ" in html)
    check("ยอดจ่ายตรงกับที่บันทึก", ">800<" in html.replace(" ", "").replace("\n", ""))
    check("ยอดรับตรงกับที่บันทึก", "15,000" in html)
    check("มีแถบหมวด", "บิล/ที่พัก" in html)
    check("เดือนถัดไปถูกปิดไว้ (ยังมาไม่ถึง)", "เดือนถัดไป →</span>" in html)

    target = db.query(Expense).filter(Expense.user_id == USER).first().id
    resp = client.post(f"/dashboard/expenses/{target}/delete", data={"month": ""},
                       follow_redirects=False)
    check("ลบจากเว็บแล้ว redirect", resp.status_code == 302)
    check("แถวถูกลบจริง", db.query(Expense).filter(Expense.id == target).first() is None)

    anon = TestClient(web.app)
    resp = anon.get("/dashboard/expenses", follow_redirects=False)
    check("ไม่ล็อกอิน → redirect ไป login", resp.status_code in (302, 307))


def main():
    init_db(retries=1)
    test_parses_money()
    test_rejects_tasks()
    test_day_offset()

    db = SessionLocal()
    try:
        test_flow(db)
        test_task_still_works(db)
        test_ownership(db)
        test_id_collision(db)
        test_web(db)
    finally:
        db.close()

    print()
    if _fail:
        print(f"❌ ไม่ผ่าน {len(_fail)} เคส:")
        for name in _fail:
            print("   -", name)
        sys.exit(1)
    print("✅ ผ่านทั้งหมด")


if __name__ == "__main__":
    main()

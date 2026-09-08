"""Test the /api plan endpoints against a throwaway SQLite DB.

    venv\\Scripts\\python.exe scripts\\test_api.py

Runs the real FastAPI app through TestClient, so routing + auth + schemas are
covered — not just the helper functions.
"""
import os
import pathlib
import sys
import tempfile
from datetime import datetime, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

_TMP = pathlib.Path(tempfile.mkdtemp(prefix="apitest_")) / "t.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP.as_posix()}"
os.environ["API_SECRET"] = "testsecret"
os.environ.pop("CRON_SECRET", None)

from fastapi.testclient import TestClient  # noqa: E402

from app.database import SessionLocal, init_db  # noqa: E402
from app.models import User  # noqa: E402
from app.parser import TZ, now_local  # noqa: E402

init_db()
db = SessionLocal()
db.add(User(line_user_id="U_test_1", display_name="Tester", plan="free"))
db.commit()
db.close()

from app.main import app  # noqa: E402

client = TestClient(app)
KEY = {"X-API-Key": "testsecret"}

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}  {detail}")


print("\n== auth ==")
check("no key -> 401", client.get("/api/tasks").status_code == 401)
check("wrong key -> 401",
      client.get("/api/tasks", headers={"X-API-Key": "nope"}).status_code == 401)
check("right key -> 200", client.get("/api/tasks", headers=KEY).status_code == 200)

print("\n== users ==")
r = client.get("/api/users", headers=KEY).json()
check("lists the seeded user", r["users"][0]["line_user_id"] == "U_test_1", r)

print("\n== create ==")
today = now_local().date()
tomorrow = today + timedelta(days=1)
r = client.post("/api/tasks", headers=KEY, json={"items": [
    {"title": "งานพรุ่งนี้ 4 โมง", "deadline": f"{tomorrow} 16:00", "priority": "high"},
    {"title": "งานวันนี้ทั้งวัน", "deadline": str(today)},
    {"title": "งานค้างไม่มีวัน", "note": "จาก MEMORY"},
]})
check("create -> 200", r.status_code == 200, r.text)
body = r.json()
check("created 3", body["created"] == 3, body)
ids = {t["title"]: t["id"] for t in body["tasks"]}
by_title = {t["title"]: t for t in body["tasks"]}
check("user_id defaulted to the only user", body["tasks"][0]["id"] > 0)
check("bare date -> 23:59 local",
      by_title["งานวันนี้ทั้งวัน"]["deadline"] == f"{today} 23:59",
      by_title["งานวันนี้ทั้งวัน"]["deadline"])
check("time kept in Bangkok tz",
      by_title["งานพรุ่งนี้ 4 โมง"]["deadline"] == f"{tomorrow} 16:00",
      by_title["งานพรุ่งนี้ 4 โมง"]["deadline"])
check("no deadline -> null (backlog)", by_title["งานค้างไม่มีวัน"]["deadline"] is None)
check("priority kept", by_title["งานพรุ่งนี้ 4 โมง"]["priority"] == "high")

print("\n== scopes ==")
def titles(scope):
    return {t["title"] for t in client.get(f"/api/tasks?scope={scope}", headers=KEY).json()["tasks"]}

check("today", titles("today") == {"งานวันนี้ทั้งวัน"}, titles("today"))
check("tomorrow", titles("tomorrow") == {"งานพรุ่งนี้ 4 โมง"}, titles("tomorrow"))
check("backlog", titles("backlog") == {"งานค้างไม่มีวัน"}, titles("backlog"))
check("week has both dated", titles("week") == {"งานวันนี้ทั้งวัน", "งานพรุ่งนี้ 4 โมง"}, titles("week"))
check("all has 3", len(titles("all")) == 3)
check("backlog sorts last in all",
      client.get("/api/tasks?scope=all", headers=KEY).json()["tasks"][-1]["deadline"] is None)
check("bad scope -> 422", client.get("/api/tasks?scope=zzz", headers=KEY).status_code == 422)

print("\n== deadline parsing ==")
r = client.post("/api/tasks", headers=KEY,
                json={"items": [{"title": "x", "deadline": "31/12/2026"}]})
check("bad format -> 422", r.status_code == 422, r.text)
r = client.post("/api/tasks", headers=KEY,
                json={"items": [{"title": "iso", "deadline": f"{tomorrow}T09:30"}]})
check("ISO 'T' accepted", r.status_code == 200 and r.json()["tasks"][0]["deadline"] == f"{tomorrow} 09:30",
      r.text)
client.delete(f"/api/tasks/{r.json()['tasks'][0]['id']}", headers=KEY)

print("\n== patch ==")
tid = ids["งานค้างไม่มีวัน"]
r = client.patch(f"/api/tasks/{tid}", headers=KEY, json={"deadline": f"{tomorrow} 09:00"})
check("backlog -> dated", r.json()["task"]["deadline"] == f"{tomorrow} 09:00", r.text)
check("now in tomorrow", "งานค้างไม่มีวัน" in titles("tomorrow"))
r = client.patch(f"/api/tasks/{tid}", headers=KEY, json={"clear_deadline": True})
check("clear_deadline -> back to backlog", r.json()["task"]["deadline"] is None)
r = client.patch(f"/api/tasks/{tid}", headers=KEY, json={"done": True})
check("done=True", r.json()["task"]["done"] is True)
check("done task leaves 'all'", "งานค้างไม่มีวัน" not in titles("all"))
check("done task appears in 'done'", "งานค้างไม่มีวัน" in titles("done"))
r = client.patch(f"/api/tasks/{tid}", headers=KEY, json={"priority": "bogus"})
check("bad priority -> 422", r.status_code == 422)
r = client.patch("/api/tasks/999999", headers=KEY, json={"done": True})
check("missing task -> 404", r.status_code == 404)

print("\n== ownership ==")
r = client.patch(f"/api/tasks/{ids['งานวันนี้ทั้งวัน']}", headers=KEY,
                 json={"user_id": "U_someone_else", "done": True})
check("other user's id -> 404", r.status_code == 404, r.text)
r = client.delete(f"/api/tasks/{ids['งานวันนี้ทั้งวัน']}?user_id=U_someone_else", headers=KEY)
check("delete as other user -> 404", r.status_code == 404)

print("\n== delete ==")
r = client.delete(f"/api/tasks/{ids['งานวันนี้ทั้งวัน']}", headers=KEY)
check("delete -> 200", r.status_code == 200 and r.json()["deleted"] == ids["งานวันนี้ทั้งวัน"], r.text)
check("gone from today", titles("today") == set())
check("delete again -> 404",
      client.delete(f"/api/tasks/{ids['งานวันนี้ทั้งวัน']}", headers=KEY).status_code == 404)

print("\n== LINE still reads the same rows ==")
from app.line_handler import handle_command  # noqa: E402

db = SessionLocal()
out = handle_command(db, "U_test_1", "พรุ่งนี้")
check("LINE 'พรุ่งนี้' sees the API-written task", "งานพรุ่งนี้ 4 โมง" in out, out)
out = handle_command(db, "U_test_1", "ทั้งหมด")
check("LINE 'ทั้งหมด' sees it too", "งานพรุ่งนี้ 4 โมง" in out, out)
db.close()

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)

# LINE Task Bot

บอทจัดการงาน/แจ้งเตือนผ่าน LINE + เว็บ dashboard — พิมพ์ภาษาไทยธรรมชาติ เช่น "พรุ่งนี้ส่งการบ้าน 4 โมง" แล้วบอทแยกวันเวลาให้เอง

- **Live:** https://line-task-bot-u5vn.onrender.com (Render free tier — เครื่องหลับเมื่อไม่มี traffic, ตื่นช้า ~1 นาที)
- **GitHub:** https://github.com/JKTor/line-task-bot (push ไป main = deploy อัตโนมัติ)
- สถานะงาน/สิ่งที่ค้างอยู่ใน `HANDOFF.md`, ประวัติการแก้ใน `CHANGELOG.md`

## โครงสร้าง (`app/`)

- `main.py` — FastAPI: webhook LINE, เว็บ dashboard, `/cron/check` (ตัวส่ง reminder ทุกประเภทรวมถึง weekly summary — ยิงโดย cron ภายนอกด้วย `CRON_SECRET`)
- `line_handler.py` — logic ตอบข้อความ LINE ทั้งหมด (คำสั่ง เพิ่ม/เสร็จ/เลื่อน/ลบ, quick reply, subscription gating free 30 task)
- `parser.py` — แยกวันเวลาไทยด้วย regex (ตัวหลัก), `ai_parser.py` — fallback ผ่าน Gemini/Groq
- `scheduler.py` — เช็ค quiet hours ก่อนส่ง reminder (รองรับช่วงข้ามเที่ยงคืน 22:00–08:00)
- `auth.py` — LINE Login OAuth + JWT cookie 30 วัน, `notion_sync.py` — sync ไป Notion (pro user เท่านั้น)
- `templates/` — Jinja2 (landing, dashboard, tasks, admin)
- DB: Postgres บน Render (SQLAlchemy) — local dev ใช้ `.env` ชี้ DATABASE_URL

## คำสั่ง (PowerShell ในโฟลเดอร์โปรเจกต์)

```powershell
# รัน local (ต้องมี .env ครบ — ดู .env.example)
venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000

# เทสต์ (สคริปต์ใน scripts/ รันตรงๆ ไม่ใช่ pytest)
venv\Scripts\python.exe scripts\test_parser_th.py
venv\Scripts\python.exe scripts\test_clarify.py
venv\Scripts\python.exe scripts\test_weekly_guard.py
venv\Scripts\python.exe scripts\check_db.py   # ดูข้อมูลใน DB
```

venv อยู่ที่ `venv/` (ไม่ใช่ `.venv`) — ใช้ `venv\Scripts\python.exe` เสมอ

## กฎ / ข้อควรระวัง

- **timezone ทั้งระบบคือ Asia/Bangkok** — เวลาใน DB และการเทียบเวลา reminder ต้องระวัง tz เสมอ
- **ห้าม commit `.env`** — secrets ทั้งหมด (LINE, JWT, ADMIN_SECRET, DATABASE_URL) อยู่ใน Render env vars, รายการ key ดู `HANDOFF.md`
- แก้ `parser.py` แล้วต้องรัน `scripts\test_parser_th.py` เสมอ — ภาษาไทยมี edge case เยอะ (พรุ่งนี้/มะรืน/บ่าย 3/4 โมงเย็น)
- webhook LINE ทดสอบ local ไม่ได้ตรงๆ (LINE ต้อง https) — ทดสอบ logic ผ่านสคริปต์ใน `scripts/` หรือ deploy ไป Render แล้วลองจริง
- reminder ทุกประเภทส่งผ่าน `/cron/check` ทางเดียว — อย่าเพิ่ม cron แยก (เคยมีบั๊ก weekly summary จาก cron แยก ดู commit 95e97e7)
- ตอบ user เป็นภาษาไทย สั้น อ่านง่ายบนมือถือ

## เมื่อแก้โค้ดเสร็จ

รันสคริปต์เทสต์ที่เกี่ยวข้องใน `scripts/` ให้ผ่านก่อน commit — ถ้าเป็น flow LINE ที่เทสต์ local ไม่ได้ ให้บอก user ว่าต้อง deploy แล้วลองในแอป LINE จริง

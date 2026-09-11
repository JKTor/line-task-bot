# LINE Task Bot

บอทจัดการงาน/แจ้งเตือนผ่าน LINE + เว็บ dashboard — พิมพ์ภาษาไทยธรรมชาติ เช่น "พรุ่งนี้ส่งการบ้าน 4 โมง" แล้วบอทแยกวันเวลาให้เอง

- **Live:** https://line-task-bot-u5vn.onrender.com (Render free tier — เครื่องหลับเมื่อไม่มี traffic, ตื่นช้า ~1 นาที)
- **GitHub:** https://github.com/JKTor/line-task-bot (push ไป main = deploy อัตโนมัติ)
- สถานะงาน/สิ่งที่ค้างอยู่ใน `HANDOFF.md`, ประวัติการแก้ใน `CHANGELOG.md`

## โครงสร้าง (`app/`)

- `main.py` — FastAPI: webhook LINE, เว็บ dashboard, `/cron/check` (ตัวส่ง reminder ทุกประเภทรวมถึง weekly summary — ยิงโดย cron ภายนอกด้วย `CRON_SECRET`)
- `handlers/` — logic ตอบข้อความ LINE ทั้งหมด (เดิมเป็นไฟล์เดียว `line_handler.py` 1,133 บรรทัด แยกเมื่อ 11 ก.ย. 69)
  - `router.py` — **ทางเข้า เริ่มอ่านที่นี่** ตัดสินว่าส่งข้อความไปชั้นไหน + จัดการสถานะรอคำตอบ
  - `strict.py` ชั้น 1 จับ pattern (ข้อความส่วนใหญ่จบตรงนี้ ไม่เรียก AI) · `ai_dispatch.py` ชั้น 2 แปลง intent จาก AI เป็นการกระทำ
  - `tasks.py` งาน · `routines.py` กิจวัตร · `money.py` รายรับ-รายจ่าย (+ `_delete_smart` จุดที่ id งานกับเงินชนกัน)
  - `clarify.py` สถานะถามกลับ + log ข้อความที่อ่านไม่ออก · `formatting.py` แปลงข้อมูลเป็นข้อความ (ไม่แตะ DB) · `constants.py` ข้อความคงที่
  - ทิศทาง import เป็นทางเดียวเสมอ router → strict/ai_dispatch → tasks → routines → formatting → constants
- `line_handler.py` — เหลือเป็นหน้ากากบางๆ re-export จาก `handlers/` ให้ของเดิมที่ `import app.line_handler` ยังใช้ได้ (โค้ดใหม่ให้ import จาก `app.handlers`)
- `parser.py` — แยกวันเวลาไทยด้วย regex (ตัวหลัก), `ai_parser.py` — fallback ผ่าน Gemini/Groq
- `scheduler.py` — เช็ค quiet hours ก่อนส่ง reminder (รองรับช่วงข้ามเที่ยงคืน 22:00–08:00)
- `auth.py` — LINE Login OAuth + JWT cookie 30 วัน, `notion_sync.py` — sync ไป Notion (pro user เท่านั้น)
- `api.py` — JSON API `/api/*` สำหรับเขียน/อ่านแผนจากนอกไลน์ (Claude Code) กันด้วย header `X-API-Key` = `API_SECRET` (ไม่ตั้งจะ fallback ไป `CRON_SECRET`) — เขียนลงตาราง `tasks` ตัวเดียวกับที่ไลน์อ่าน จงใจ **ไม่** บังคับโควตา free 30 task เพราะคีย์นี้เป็นของเจ้าของบอท
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
venv\Scripts\python.exe scripts\test_api.py   # /api/* (35 เคส ผ่าน TestClient)
venv\Scripts\python.exe scripts\check_db.py   # ดูข้อมูลใน DB
```

จัดการแผนจากเครื่อง (เรียก API บน prod, stdlib ล้วน ไม่ต้อง venv):

```powershell
python C:\Users\data2\.claude\plan.py list tomorrow
python C:\Users\data2\.claude\plan.py add "ส่งงาน" --date 2026-09-12 --time 16:00 --pri high
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

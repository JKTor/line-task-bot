# LINE Task Bot — Handoff

**Live URL:** https://line-task-bot-u5vn.onrender.com  
**GitHub:** https://github.com/JKTor/line-task-bot

---

## ✅ เสร็จทั้งหมดแล้ว (commit af0d428)

### สิ่งที่ทำเสร็จ

**User System:**
- `User` model: plan (free/pro/team), plan_expires_at, notion_token, quiet_start/end
- Auto-create user เมื่อ message ครั้งแรก + onboarding message
- Subscription gating: free user ได้ 30 task, เกินแล้วบอกให้ upgrade

**LINE Login OAuth (`app/auth.py`):**
- `GET /auth/line` → redirect LINE
- `GET /auth/callback` → JWT session cookie (30 วัน)
- `GET /auth/logout`

**Web Dashboard:**
- `GET /` → Landing page (feature list + pricing)
- `GET /dashboard` → Settings (plan status, Notion token, quiet hours)
- `GET /dashboard/tasks` → ดู task จาก LINE บนเว็บ (same DB, real-time)
- `GET /admin?secret=ADMIN_SECRET` → user list, activate plan

**Admin:**
- `POST /admin/activate` → set plan + expiry (manual payment flow)

**Quick Reply Buttons (commit af0d428):**
- หลังเพิ่มงาน มีปุ่ม [✅ เสร็จ #id] [📅 เลื่อน #id] [🗑️ ลบ #id]
- แก้ bug: subscription gating `continue` ผิดตำแหน่ง ทำให้คำสั่ง "เพิ่ม" ไม่ถูก process

**Notion Sync (commit af0d428):**
- `app/notion_sync.py` — sync task ไป Notion อัตโนมัติเมื่อเพิ่มงาน
- เฉพาะ pro user ที่มี notion_token + notion_db_id ใน dashboard
- sync ชื่องาน + Due Date (ถ้า database มี property ชื่อ "Due Date")

**Quiet Hours enforcement (commit af0d428):**
- `scheduler.py` เช็ค quiet_start/quiet_end ก่อนส่ง reminder ทุกประเภท
- รองรับช่วงที่ข้ามเที่ยงคืน เช่น 22:00–08:00

---

## 🔧 สิ่งที่ต้องทำก่อนใช้งานจริง

### 1. ตั้ง ENV ใหม่ใน Render

| Key | ค่า | ที่มา |
|-----|-----|------|
| `LINE_LOGIN_CLIENT_ID` | Channel ID | LINE Dev Console → LINE Login channel |
| `LINE_LOGIN_SECRET` | Channel Secret | LINE Dev Console |
| `JWT_SECRET` | random 32 chars | `openssl rand -hex 32` |
| `APP_BASE_URL` | `https://line-task-bot-u5vn.onrender.com` | URL ของ Render |
| `ADMIN_SECRET` | random string | ตั้งเอง |

### 2. Setup LINE Login Channel (LINE Developer Console)
1. ไป developers.line.biz
2. สร้าง **LINE Login channel** ใหม่ (ต่างจาก Messaging API)
3. ตั้ง Callback URL: `https://line-task-bot-u5vn.onrender.com/auth/callback`
4. เปิด scope: `profile`, `openid`
5. Copy Client ID + Secret → ใส่ใน Render ENV

### 3. ทดสอบ
```
GET  /                              → เห็น landing page
GET  /auth/line                     → redirect LINE Login
GET  /dashboard                     → settings page (ต้อง login ก่อน)
GET  /dashboard/tasks               → เห็น task จาก LINE
GET  /admin?secret=ADMIN_SECRET     → user list
POST /admin/activate                → activate plan manually
```

---

## ✅ พร้อมใช้งานจริงแล้ว

- ENV 5 ตัวตั้งใน Render แล้ว ✅
- LINE Login Channel สร้างและตั้ง Callback URL แล้ว ✅

---

## ✅ ปรับปรุงฟรีเพื่อให้พร้อมขายมากขึ้น (2026-05-20)

### Cron/Render free tier
- ตั้ง cron-job.org สำเร็จแล้ว 4 งาน:
  - `LINE Task Bot Health` → `/health` ทุก 5 นาที เพื่อช่วยกัน Render หลับ
  - `LINE Task Bot Reminder` → `/cron/check?...` ทุก 5 นาที
  - `LINE Task Bot Morning` → `/cron/morning?...` ทุกวัน 08:00 เวลาไทย
  - `LINE Task Bot Weekly` → `/cron/weekly?...` ทุกวันจันทร์ 08:00 เวลาไทย
- ทดสอบแล้ว:
  - `/health` ได้ `{"status":"ok"}`
  - `/cron/check` ได้ `{"ok":true,"reminders_sent":0}`
  - `/cron/morning` ได้ `{"ok":true,"sent":1}`
  - `/cron/weekly` ได้ `{"ok":true,"sent":1}`
- ปรับ `app/main.py` ให้ internal APScheduler ปิดเป็นค่าเริ่มต้น เพื่อไม่ให้ส่ง reminder ซ้ำกับ cron-job.org
- ถ้าต้องการเปิด scheduler ในแอปจริง ให้ตั้ง ENV `ENABLE_INTERNAL_SCHEDULER=true`

### LINE UX / Bot intelligence
- ปรับ `app/line_handler.py` ให้คำสั่งดูตาราง เช่น `วันนี้`, `พรุ่งนี้`, `อาทิตย์นี้`, `list_date` รวมทั้ง `Task` และ `Routine`
- ลดเคสที่บอทตอบผิดว่า "(ไม่มีงาน)" ทั้งที่มีกิจวัตร เช่น `ออกกำลังกาย`
- เพิ่มตัวจับข้อความแบบ schedule statement เช่น `วันพรุ่งนี้ มีออกกำลังกายตอน สี่โมงเย็น` เพื่อไม่ให้ strict matcher รีบตีความเป็นคำถามดูงานพรุ่งนี้อย่างเดียว และปล่อยให้ AI parser ตีความต่อ

### ทดสอบ local
- `python -m compileall app` ผ่าน
- จำลอง routine `ออกกำลังกาย` แล้วเรียก `_list_tomorrow()` ได้ผลลัพธ์ที่รวมกิจวัตร

---

## ✅ Database: อยู่บน Postgres (Neon) แล้ว (2026-07-06)

- `DATABASE_URL` ใน Render ชี้ Neon Postgres (`ap-southeast-1`, project `line-task-bot`)
- ยืนยันจาก log ตอน boot: `[db] using sslmode=require` (branch `_is_pg`)
- ตารางครบใน Neon: `users`, `tasks`, `routines`, `unknown_messages` — สร้างอัตโนมัติโดย `init_db()`
- **ข้อมูลไม่หายตอน redeploy อีกต่อไป** (ปัญหา SQLite ephemeral เดิมจบแล้ว)
- ทดสอบ connection string ใหม่ได้ด้วย `python scripts/check_db.py` (ตั้ง `DATABASE_URL` ก่อนรัน)
- `database.py` มี warning ถ้าเผลอ deploy จริงบน SQLite

---

## 🔒 Auth security hardening เสร็จแล้ว (commit f8abb4e, 2026-07-06)

- ตรวจ LINE OAuth `state` ที่ `/auth/callback` (กัน CSRF / login fixation)
- cookie `Secure` อัตโนมัติบน HTTPS deploy
- `/debug/ai` ต้องใส่ `ADMIN_SECRET`
- warning ถ้า `JWT_SECRET` ยังเป็นค่า default ใน production

---

## ✅ Clarify flow เสร็จแล้ว (PRD §21, 2026-07-06)

"เตือนส่งเอกสาร" (ไม่บอกวัน) → บอทถาม "📅 อยากให้เตือนวันไหน?" → user ตอบ "พรุ่งนี้ 17:00" → บอทสร้างงานให้
- `ai_parser.py`: เพิ่ม intent `clarify` (คืนเฉพาะคำสั่งเตือน/ตั้งงานที่ขาดวัน-เวลา ไม่ over-trigger กับ "จดไว้/ไม่รีบ")
- state เก็บในตารางใหม่ `PendingClarify` (1 row/user, TTL 10 นาที) — สร้างอัตโนมัติโดย `create_all` ตอน deploy
- `line_handler.handle_command`: เช็ค pending ก่อน → ข้อความถัดไปถือเป็นคำตอบ merge กับ title เดิมแล้วส่งเข้า pipeline เดิม (`allow_clarify=False` กัน loop); พิมพ์ "ยกเลิก" = ล้าง pending
- ทดสอบครบ 6 เคสด้วย `python scripts/test_clarify.py` (mock AI, ผ่านหมด)

## ✅ เสร็จเพิ่ม (2026-07-06 รอบ review+TODO)

- **แก้บั๊ก clarify cancel:** `_CANCEL_WORDS` เดิมเช็คแบบ substring → คำว่า "เลิก" ใน "หลังเลิกงาน 6 โมง" ทำให้บอทยกเลิกงานผิด. เปลี่ยนเป็น `_is_cancel()` ที่ match ทั้งข้อความ/startswith "ยกเลิก" เท่านั้น
- **กัน pending hijack:** เพิ่ม `_looks_like_fresh_command()` — ถ้าระหว่างรอตอบวัน ผู้ใช้พิมพ์คำสั่งชัดเจน (งานวันนี้/ทั้งหมด/กิจวัตร/ช่วยเหลือ) จะรันคำสั่งนั้นแทนที่จะเอาไป merge เป็น title
- **✅ รวม routine ในหน้า `/dashboard/tasks`:** route query routine + filter ตาม weekday (today/tomorrow), แยก section "📋 งาน" / "🔔 กิจวัตร" ใน `tasks.html`
- **✅ หน้า admin unknown messages:** แปลง `/admin/unknown` จาก JSON → HTML (`unknown.html`) ใช้ `ADMIN_SECRET` (เดิมเช็ค CRON_SECRET ทำให้ลิงก์ใน admin.html พัง), มี tab ยังไม่จัดการ/จัดการแล้ว + ปุ่ม resolve
- **✅ tests parser ภาษาไทย:** `scripts/test_parser_th.py` (pure, ไม่ต้อง AI/DB) — parse_task + guard ต่างๆ 25 เคส ผ่านหมด
- ⚠️ รัน test บน Windows ต้องตั้ง `$env:PYTHONIOENCODING="utf-8"` ก่อน (console cp1252 พัง emoji)

## 🟡 TODO ที่ยังเหลือ

- routine ในหน้า tasks ยังเป็น read-only + filter overdue ไม่โชว์ routine (ตั้งใจ)
- ปรับ prompt/parser จากข้อมูล unknown messages ที่เก็บได้

---

## Cron Jobs (cron-job.org)

| Endpoint | Schedule |
|----------|----------|
| `/health` | ทุก 5 นาที |
| `/cron/check?secret=CRON_SECRET` | ทุก 5 นาที |
| `/cron/morning?secret=CRON_SECRET` | ทุกวัน 08:00 เวลาไทย |
| `/cron/weekly?secret=CRON_SECRET` | ทุกวันจันทร์ 08:00 เวลาไทย |

---

## โครงสร้างไฟล์

```
app/
├── models.py       Task, Routine, UnknownMessage, User
├── database.py     engine + SSL fix + migrate_db()
├── auth.py         LINE Login OAuth + JWT session
├── middleware.py   subscription gating
├── line_handler.py handlers + AI dispatch + quick reply
├── notion_sync.py  Notion integration ← ใหม่
├── ai_parser.py    SYSTEM_PROMPT + Groq/Gemini
├── scheduler.py    reminders + digest + quiet hours
├── parser.py       Thai date/time regex
└── main.py         FastAPI + web routes + webhook
app/templates/
├── base.html      nav + layout
├── landing.html   หน้าแรก + pricing
├── dashboard.html settings + plan
├── tasks.html     task list จาก LINE
└── admin.html     admin panel
```

## Pricing Model

| Plan | ราคา | Limits |
|------|------|--------|
| Free | ฿0 | 30 active tasks |
| Pro | ฿99/เดือน | unlimited + Notion sync + quiet hours |
| Team | ฿299/เดือน | 5 users + all Pro features |

**Payment flow (manual):** ลูกค้าโอน PromptPay → แจ้ง → admin activate via `/admin?secret=ADMIN_SECRET`

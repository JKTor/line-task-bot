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

## 🟡 TODO เพิ่มเติม (ทำทีหลังได้)

### Clarify missing info (PRD §21)
"เตือนส่งเอกสาร" → บอทถาม "ให้เตือนวันไหน?"
- ต้องแก้ `ai_parser.py` SYSTEM_PROMPT ให้ return intent = "clarify" เมื่อข้อมูลไม่ครบ
- webhook ใน `main.py` ต้องเก็บ context ของ conversation ไว้ชั่วคราว (ตอนนี้ stateless)

### ทำให้เหมาะกับการขายมากขึ้นแบบยังไม่เสียเงิน
- เพิ่ม clarify flow แบบ state ชั่วคราว เช่น user พิมพ์ `เตือนส่งเอกสาร` แล้วบอทถามวัน/เวลา
- รวม routine ในหน้า `/dashboard/tasks` หรือทำหน้า agenda ใหม่ที่รวม task + routine
- เพิ่มหน้า admin ดู unknown messages ให้ใช้ง่ายขึ้น และใช้ข้อมูลนั้นปรับ prompt/parser
- เพิ่ม tests สำหรับ parser/handler เคสภาษาไทยธรรมชาติ
- ปรับ auth security: ตรวจ LINE OAuth `state`, ตั้ง cookie `secure=True`, และบังคับ `JWT_SECRET` ใน production

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

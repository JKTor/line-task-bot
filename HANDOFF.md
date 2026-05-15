# LINE Task Bot — Handoff

**Live URL:** https://line-task-bot-u5vn.onrender.com  
**GitHub:** https://github.com/JKTor/line-task-bot

---

## ✅ SaaS Foundation เสร็จแล้ว (commit 09b2080)

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

## 🔧 TODO ต่อใน session หน้า

### 1. Quick Reply Buttons (PRD §20)
หลังเพิ่มงาน ให้มีปุ่ม [เสร็จแล้ว] [เลื่อน] [ลบ]

**วิธีทำ:**
- แก้ `handle_command` → return dict แทน str:
  `{"text": "...", "quick_reply": [{"label": "เสร็จแล้ว 1", "text": "เสร็จ 1"}]}`
- แก้ webhook ใน `main.py` ใช้ `QuickReply` จาก LINE SDK:
  ```python
  from linebot.v3.messaging import QuickReply, QuickReplyItem, MessageAction
  ```
- Files: `app/line_handler.py`, `app/main.py`

### 2. Notion Sync
เมื่อ user มี notion_token → sync task ไป Notion อัตโนมัติ
- แก้ `_add_task` ใน line_handler.py → เรียก `notion_sync.create_page()`
- สร้าง `app/notion_sync.py`
- install: `notion-client`

### 3. Clarify missing info (PRD §21)
"เตือนส่งเอกสาร" → บอทถาม "ให้เตือนวันไหน?"

### 4. Quiet Hours enforcement
ตอนส่ง reminder → เช็ค user.quiet_start และ user.quiet_end ก่อน
- แก้ `check_and_send_reminders` และ `check_routine_reminders` ใน `scheduler.py`

---

## Cron Jobs (cron-job.org)

| Endpoint | Schedule UTC |
|----------|-------------|
| `/cron/check?secret=mybot_cron_a8f3k2j9` | ทุก 5 นาที |
| `/cron/morning?secret=mybot_cron_a8f3k2j9` | ทุกวัน 01:00 |
| `/cron/weekly?secret=mybot_cron_a8f3k2j9` | อาทิตย์ 01:00 |

---

## โครงสร้างไฟล์

```
app/
├── models.py      Task, Routine, UnknownMessage, User
├── database.py    engine + SSL fix + migrate_db()
├── auth.py        LINE Login OAuth + JWT session ← ใหม่
├── middleware.py  subscription gating ← ใหม่
├── line_handler.py handlers + AI dispatch
├── ai_parser.py   SYSTEM_PROMPT + Groq/Gemini
├── scheduler.py   reminders + digest
├── parser.py      Thai date/time regex
└── main.py        FastAPI + web routes + webhook
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

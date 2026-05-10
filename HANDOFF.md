# LINE Task Bot — Handoff

โปรเจกต์: LINE chatbot จัดการงาน + เตือน deadline สำหรับใช้ส่วนตัว

## 🚀 สถานะปัจจุบัน (deployed & ใช้งานได้)

- **Live URL**: https://line-task-bot-u5vn.onrender.com
- **Repo**: https://github.com/JKTor/line-task-bot
- **Hosting**: Render free tier (sleep หลัง 15 นาที, cron-job.org ปลุกทุก 5 นาที)
- **Database**: SQLite (data หายเมื่อ Render redeploy — ดู TODO ด้านล่าง)

## 🧠 Stack

- **Backend**: FastAPI + SQLAlchemy + line-bot-sdk v3
- **AI parser**: Groq (Llama 3.3 70B) เป็นหลัก, fallback ไป Gemini
- **Cron**: cron-job.org → ping `/cron/check?secret=...` ทุก 5 นาที

## 🔑 Environment Variables ที่ต้องตั้งใน Render

| Key | หมายเหตุ |
|---|---|
| `LINE_CHANNEL_SECRET` | จาก LINE Developer Console |
| `LINE_CHANNEL_ACCESS_TOKEN` | จาก LINE Developer Console |
| `GROQ_API_KEY` | จาก console.groq.com (AI หลัก) |
| `GEMINI_API_KEY` | จาก aistudio.google.com (AI สำรอง — Thailand region ใช้ไม่ได้) |
| `DATABASE_URL` | `sqlite:///./tasks.db` (default) |
| `CRON_SECRET` | random string สำหรับ protect /cron/check |
| `TIMEZONE` | `Asia/Bangkok` |

## 💬 คำสั่งที่บอทเข้าใจ

**คำสั่งตรงๆ (regex, เร็ว):**
- `เพิ่ม <งาน> [วันเวลา]` — เช่น `เพิ่ม ส่งรายงาน 10/5 18:00`
- `วันนี้` — ดูงานวันนี้
- `ทั้งหมด` — ดูงานที่ค้าง
- `เสร็จ <id>` — ทำเครื่องหมายเสร็จ
- `ลบ <id>` — ลบ
- `ช่วยเหลือ`

**ภาษาธรรมชาติ (AI parser, ช้าลงนิด):**
- `พรุ่งนี้ลืมส่ง hw 6 โมงเย็นด้วย`
- `อ่านหนังสือ 4 ทุ่ม` → 22:00
- `ตื่นตี 5 พรุ่งนี้`
- `ลบงานทั้งหมด` → ล้าง list ทั้งหมด
- `เสร็จหมดแล้ว` → ปิดงานทั้งหมด
- `มีงานวันนี้ 3 อย่าง อ่านหนังสือ ทำการบ้าน ส่งรายงานเที่ยง` → เพิ่มทีละ 3 ตัว

## 📁 โครงสร้างไฟล์

```
line-task-bot/
├── app/
│   ├── main.py           # FastAPI + LINE webhook endpoint
│   ├── line_handler.py   # dispatch คำสั่ง: regex strict ก่อน, AI fallback
│   ├── ai_parser.py      # Groq + Gemini wrappers, Thai time prompt
│   ├── parser.py         # regex parser (DD/MM, HH:MM, "วันนี้/พรุ่งนี้")
│   ├── scheduler.py      # check_and_send_reminders() — เรียกจาก /cron/check
│   ├── database.py       # SQLAlchemy engine + session
│   └── models.py         # Task model
├── requirements.txt
├── render.yaml           # Render Blueprint config
├── Procfile              # start command
├── runtime.txt           # Python 3.11.9
├── .env.example          # template (ไม่มี value จริง)
└── .env                  # values จริง (ไม่ commit, อยู่ใน .gitignore)
```

## 🛠️ วิธีอัปเดตโค้ด

```powershell
cd C:\Users\LAPTOP\line-task-bot
# แก้โค้ด...
git add .
git commit -m "what you changed"
git push
# Render auto-redeploys ภายใน 2-3 นาที
```

## ✅ TODO / ไอเดียอัปเดต

### High priority
- [ ] **Database persistence**: ตอนนี้ SQLite บน Render free → data หายเมื่อ redeploy
  - แก้ด้วย Postgres ฟรีของ Neon (https://neon.tech) → set `DATABASE_URL` เป็น postgres URL
- [ ] **เพิ่ม regex รู้จัก Thai time**: ตอนนี้ "4 ทุ่ม" ต้องพึ่ง AI ทำให้ช้าและกิน quota
  - เพิ่มใน `app/parser.py` ให้ regex รู้จัก "ทุ่ม/บ่าย/ตี/เย็น/เช้า"

### Nice to have
- [ ] **Recurring tasks**: "ทุกวันจันทร์ 9 โมง ประชุมทีม"
- [ ] **Quick reply buttons** ตอนแสดง list — กดปุ่มเพื่อ mark done/delete
- [ ] **Rich menu** — เมนูหลักอยู่ด้านล่างหน้าแชท
- [ ] **Group chat support** — ตอนนี้รองรับ 1-on-1 เท่านั้น
- [ ] **Snooze reminder** — "เลื่อนงาน #3 ไปอีก 1 ชั่วโมง"
- [ ] **Stats** — สรุปจำนวนงานเสร็จต่อสัปดาห์
- [ ] **Voice message** — แปลง voice เป็น text แล้วเพิ่ม task

## 🧪 Debug Endpoints (พิมพ์ใน browser ดูได้)

- `GET /` — ping ทดสอบบอทตื่น
- `GET /health` — health check
- `GET /debug/ai` — เช็คว่า env vars ครบมั้ย (ไม่โชว์ค่าจริง)
- `GET /cron/check?secret=YOUR_CRON_SECRET` — manual trigger reminder

## 🐛 ปัญหาที่เจอแล้วแก้ไปแล้ว (อย่าทำซ้ำ)

1. **Gemini ใน Thailand**: `gemini-2.5-flash-lite` / `gemini-2.5-flash` → "User location not supported" 🚫 — ไม่ใช้ Gemini เป็นหลัก
2. **Strict parser ครอบจักรวาล**: เดิม `เพิ่ม X` ทุกอย่างจะไป regex parser ที่ไม่รู้ Thai time → แก้ให้ตรวจคำเวลาไทยและ fall through ไป AI
3. **Fallback bug**: เดิม Groq ตอบ `intent=unknown` (ถูกต้อง) → โค้ดเข้าใจผิดว่าพัง → fallback ไป Gemini → error
4. **LINE auto-reply**: ต้องไปปิดที่ manager.line.biz (ไม่ใช่ developers.line.biz)

## 🔄 รอบหน้าเริ่มยังไง

พิมพ์ใน Claude Code อะไรก็ได้ในนี้ — ผมจะอ่าน HANDOFF.md อัตโนมัติ:

- "ช่วยอ่าน HANDOFF.md ในโปรเจกต์ line-task-bot ให้หน่อย แล้วทำ TODO ข้อแรก"
- "เพิ่ม recurring task ในบอท"
- "ย้ายไป Postgres ฟรีของ Neon"
- "เพิ่ม rich menu"

หรือถ้าจำไม่ได้ก็พิมพ์: **"ทำต่อกับ LINE task bot"** ผมก็จะหาเองครับ

---
_สร้างเมื่อ 2026-05-10 หลัง deploy ครั้งแรกสำเร็จ_

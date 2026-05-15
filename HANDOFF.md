# LINE Task Bot — Handoff

**Live URL:** https://line-task-bot-u5vn.onrender.com  
**GitHub:** https://github.com/JKTor/line-task-bot  
**Stack:** Python 3.11 / FastAPI / SQLAlchemy / PostgreSQL (Neon) / Render

---

## สถานะปัจจุบัน ✅ พร้อมใช้งาน

---

## ฟีเจอร์ที่มีทั้งหมด

| ฟีเจอร์ | คำสั่ง |
|---------|--------|
| เพิ่มงาน | "เพิ่ม ส่งรายงาน พรุ่งนี้ 18:00" |
| งานวันนี้/พรุ่งนี้/อาทิตย์นี้ | "วันนี้" / "พรุ่งนี้" / "อาทิตย์นี้" |
| งานที่เลยกำหนด | "งานค้าง" / "เลยกำหนดมีอะไร" |
| งานวันที่ X | "งานวันที่ 20" / "25 พ.ค. มีงานอะไร" |
| งานทั้งหมด | "ทั้งหมด" |
| mark เสร็จ | "เสร็จ 3" |
| ลบงาน | "ลบ 3" |
| เลื่อน deadline | "เลื่อนงาน 3 เป็นพรุ่งนี้ 20:00" |
| งานซ้ำ | "ส่งรายงานทุกวันศุกร์ 5 โมงเย็น" |
| ยกเลิกซ้ำ | "ยกเลิกซ้ำ 3" |
| กิจวัตร (routine) | "ออกกำลังกายทุกวัน 18.00" |
| ดู/ลบ/แก้กิจวัตร | "กิจวัตร" / "ลบกิจวัตร 1" / "แก้กิจวัตร 1 เป็น 19:00" |
| Morning digest | auto 8 โมงเช้า (/cron/morning) |
| Weekly summary | auto อาทิตย์ 8 โมง (/cron/weekly) |

---

## Cron Jobs (cron-job.org)

| Endpoint | Schedule UTC | หมายเหตุ |
|----------|-------------|---------|
| `/cron/check?secret=...` | ทุก 5 นาที | reminders + routine alerts |
| `/cron/morning?secret=...` | ทุกวัน 01:00 | morning digest |
| `/cron/weekly?secret=...` | อาทิตย์ 01:00 | weekly summary |

---

## ถ้าผู้ใช้แจ้งว่า "ใช้ไม่ได้" — ทำตามนี้

### 1. บอทไม่ตอบเลย
```
GET /health → ต้องได้ {"status":"ok"}
```
- ถ้า 503 → Render กำลัง deploy รอ 3-5 นาที
- ถ้า timeout → Render หลับ (free tier) รอ 30 วินาทีแล้วลองใหม่

### 2. บอทตอบ "เกิดข้อผิดพลาด"
```
GET /admin/unknown?secret=mybot_cron_a8f3k2j9
```
ดูว่า user พิมอะไร → ตรวจสอบ Render Logs → แก้ code

สาเหตุที่พบบ่อย:
- DB connection หลุด → restart Render service
- SSL error จาก Neon → ดู database.py ว่า sslmode ถูกต้อง
- AI ส่ง format ผิด → ตรวจ logs

### 3. Cron ไม่ยิง (ไม่ได้รับข้อความเช้า/สัปดาห์)
```
GET /cron/morning?secret=mybot_cron_a8f3k2j9 → ต้องได้ {"ok":true}
```
- ถ้า 500 → DB มีปัญหา ดูข้อ 2
- ถ้า sent=0 → ไม่มีงานหรือ routine ในวันนั้น (ปกติ)
- ถ้า cron-job.org ไม่ยิง → เข้า dashboard ตรวจสอบ

### 4. ดู unknown messages (สิ่งที่บอทตอบไม่ได้)
```
GET /admin/unknown?secret=mybot_cron_a8f3k2j9
```
→ เห็น list → นำ text มาปรับปรุง AI prompt หรือเพิ่ม handler

---

## โครงสร้างโค้ดสำคัญ

```
app/
├── models.py        Task, Routine, UnknownMessage (DB tables)
├── database.py      engine + migrate_db() — SSL fix สำหรับ Neon
├── line_handler.py  _try_strict() → _dispatch_ai() — logic ทั้งหมด
├── ai_parser.py     SYSTEM_PROMPT + Groq/Gemini fallback
├── scheduler.py     cron functions (reminders/morning/weekly)
├── parser.py        Thai date/time regex parser
└── main.py          FastAPI endpoints + admin routes
```

### จะเพิ่ม intent ใหม่ทำยังไง
1. เพิ่ม handler `_xxx(db, user_id, ...)` ใน `line_handler.py`
2. เพิ่มใน `_dispatch_ai()` → `if action == "xxx": return _xxx(...)`
3. เพิ่มตัวอย่างใน `SYSTEM_PROMPT` ใน `ai_parser.py`
4. (Optional) เพิ่ม pattern ใน `_try_strict()` สำหรับ common phrases

### จะแก้ AI เข้าใจผิดทำยังไง
→ แก้ `SYSTEM_PROMPT` ใน `app/ai_parser.py`  
→ เพิ่ม/แก้ตัวอย่างในส่วน "ตัวอย่าง tasks/routines"

---

## Environment Variables (Render)

| Key | ที่มา |
|-----|------|
| `LINE_CHANNEL_SECRET` | LINE Developer Console |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Developer Console |
| `DATABASE_URL` | Neon.tech → Connection String |
| `CRON_SECRET` | ตั้งเอง: `mybot_cron_a8f3k2j9` |
| `GROQ_API_KEY` | console.groq.com |
| `GEMINI_API_KEY` | aistudio.google.com |

⚠️ DATABASE_URL ต้องมี `sslmode=require` ครบ ถ้า error "invalid sslmode requ" → ตรวจ Render ENV

---

## งานที่ยังไม่ได้ทำ (nice to have)

- [ ] Rich menu / Quick reply buttons บน LINE
- [ ] Export งานเป็น PDF/CSV
- [ ] แชร์งานระหว่าง user
- [ ] Snooze reminder ("เตือนอีกครั้งใน 30 นาที")
- [ ] PostgreSQL → migrate ไป Neon paid tier เพื่อ uptime ดีขึ้น
- [ ] ย้ายจาก Render free → paid tier เพื่อไม่มี sleep

---

## Commit ล่าสุด

```
19d1e93  feat: self-learning loop (unknown message logging)
128b136  feat: list_overdue, list_date, snooze, update_routine
8d25cbe  feat: list_tomorrow, list_week
0d03dc2  fix+feat: QA pass — crash fixes + AI prompt rewrite
004bd64  cleanup: remove debug endpoints
569cb65  fix: normalize sslmode via connect_args (Neon fix)
```

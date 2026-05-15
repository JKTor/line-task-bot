# LINE Task Bot — Handoff

**Live URL:** https://line-task-bot-u5vn.onrender.com  
**GitHub:** https://github.com/JKTor/line-task-bot  
**Stack:** Python 3.11 / FastAPI / SQLAlchemy / PostgreSQL (Neon) / Render

---

## สถานะ PRD ✅/🔧/⏳

| # | หัวข้อ | สถานะ |
|---|--------|--------|
| 1 | เพิ่มงานด้วยภาษาธรรมชาติ | ✅ |
| 2 | ตั้ง reminder | ✅ |
| 3 | Recurring task | ✅ |
| 4 | เตือนซ้ำจนกว่างานจะเสร็จ | ✅ check_overdue_followup() |
| 5 | ดูรายการงาน (วันนี้/พรุ่งนี้/อาทิตย์/ค้าง/ทั้งหมด) | ✅ |
| 6 | ปิดงาน | ✅ partial (missing in_progress/canceled) |
| 7 | เลื่อนงาน/snooze | ✅ |
| 8 | แยก due date กับ reminder | ⏳ deferred |
| 9 | Label/note | ✅ note field + add_note |
| 10 | Priority (urgent/high/normal/low) | ✅ priority field + list_urgent |
| 11 | มอบหมายงานกลุ่ม | ⏳ deferred |
| 12 | Private vs group | ⏳ deferred |
| 13 | สร้าง task จากแชต | ⏳ deferred |
| 14 | สรุปงานรายวัน/สัปดาห์ | ✅ |
| 15 | Subtasks | ⏳ deferred |
| 16 | AI recommendations | ⏳ deferred |
| 17 | Calendar integration | ⏳ deferred |
| 18 | แนบโน้ต/ลิงก์ | ✅ note field |
| 19 | Voice/OCR | ⏳ deferred |
| 20 | Quick Reply / Rich Menu | 🔧 **TODO NEXT SESSION** |
| 21 | ถามกลับเมื่อข้อมูลไม่ครบ | 🔧 **TODO NEXT SESSION** |
| 22 | ลบงาน | ✅ |
| 23 | ค้นหางาน | ✅ _search_tasks() |
| 24 | Export | ⏳ deferred |
| 25 | ตั้งค่า quiet hours | ⏳ deferred |
| 26 | รองรับภาษาไทย | ✅ |
| 27 | Error handling + self-learning | ✅ unknown_messages table |

---

## คำสั่งทั้งหมดที่บอทรองรับ

### Tasks
| พิมพ์ | ผลลัพธ์ |
|-------|---------|
| เพิ่ม [งาน] [เวลา] | เพิ่มงาน |
| "งานด่วน ส่งสัญญาก่อนเที่ยง" | เพิ่มงาน + priority urgent |
| วันนี้ / พรุ่งนี้ / อาทิตย์นี้ | ดูงาน |
| งานค้าง / เลยกำหนด | งานที่เลย deadline |
| งานด่วน / urgent | งาน priority urgent+high |
| หางาน [keyword] | ค้นหางาน |
| ทั้งหมด | งานทั้งหมด |
| เสร็จ [id] | mark done |
| ลบ [id] | ลบงาน |
| เลื่อนงาน [id] เป็น [วันเวลา] | เลื่อน deadline |
| เพิ่มโน้ต [id] [ข้อความ] | แนบโน้ต |
| ตั้งงาน [id] เป็น urgent | เปลี่ยน priority |

### Routines
| พิมพ์ | ผลลัพธ์ |
|-------|---------|
| "[ชื่อ]ทุกวัน [เวลา]" | เพิ่มกิจวัตร |
| กิจวัตร | ดูกิจวัตร |
| แก้กิจวัตร [id] เป็น [เวลา] | แก้เวลา |
| ลบกิจวัตร [id] | ลบ |

---

## Cron Jobs (cron-job.org)

| Endpoint | Schedule UTC |
|----------|-------------|
| `/cron/check?secret=...` | ทุก 5 นาที |
| `/cron/morning?secret=...` | ทุกวัน 01:00 |
| `/cron/weekly?secret=...` | อาทิตย์ 01:00 |

---

## 🔧 TODO ต่อใน session หน้า

### 1. Quick Reply Buttons (PRD §20) — สำคัญมาก
หลังเพิ่มงาน ให้มีปุ่ม [เสร็จแล้ว] [เลื่อน] [ลบ]
หลัง list งาน ให้มีปุ่ม [เพิ่มงาน] [งานค้าง] [กิจวัตร]

**วิธีทำ:**
- แก้ `handle_command` ให้ return `dict` แทน `str`:
  `{"text": "...", "quick_reply": [{"label": "เสร็จแล้ว", "text": "เสร็จ {id}"}]}`
- แก้ webhook ใน `main.py` ให้ build `QuickReply` จาก LINE SDK:
  ```python
  from linebot.v3.messaging import QuickReply, QuickReplyItem, MessageAction
  ```
- Line: `app/line_handler.py` + `app/main.py`

### 2. Clarify missing info (PRD §21) — สำคัญ
เมื่อ user พิม "เตือนส่งเอกสาร" (ไม่มีเวลา) ให้บอทถามกลับว่า "ให้เตือนวันไหน?"
เมื่อ user พิม "เลื่อนอันนั้น" ให้บอทแสดงงานล่าสุดให้เลือก

**วิธีทำ:**
- เพิ่ม `clarify` intent ใน ai_parser.py:
  `{"intent": "clarify", "missing": "deadline", "partial_title": "ส่งเอกสาร"}`
- เพิ่ม in-memory context dict: `_user_context: Dict[str, dict] = {}`
  เก็บ `{"pending_task": {...}, "last_tasks": [...]}`
- ใน `_dispatch_ai`: ถ้า `clarify` → บันทึก pending แล้วถาม
- ใน `handle_command`: ถ้ามี pending context → ลอง resolve ก่อน
- File: `app/line_handler.py`, `app/ai_parser.py`

### 3. Status: in_progress / canceled (PRD §6)
เพิ่ม `status` column: todo/in_progress/done/canceled
- `เริ่มทำ [id]` → status = in_progress
- `ยกเลิก [id]` → status = canceled (ไม่ลบ, แค่ archive)
- File: `app/models.py`, `app/database.py`, `app/line_handler.py`

---

## Troubleshooting

### บอทไม่ตอบ
→ `GET /health` ถ้า 503 = กำลัง deploy รอ 3-5 นาที

### เกิดข้อผิดพลาด
→ `GET /admin/unknown?secret=mybot_cron_a8f3k2j9`

### Cron ไม่ยิง
→ `GET /cron/morning?secret=mybot_cron_a8f3k2j9`

### SSL error "invalid sslmode requ"
→ ตรวจ DATABASE_URL ใน Render ENV ว่า `sslmode=require` ครบ

---

## โครงสร้างไฟล์

```
app/models.py        Task(priority,note,overdue_notified_date) + Routine + UnknownMessage
app/database.py      migrate_db() — SSL fix + column migrations
app/line_handler.py  handlers + _dispatch_ai + _try_strict
app/ai_parser.py     SYSTEM_PROMPT + Groq/Gemini
app/scheduler.py     check_and_send + overdue_followup + routine + morning + weekly
app/main.py          FastAPI endpoints + admin routes
```

## ENV Variables

| Key | ค่า |
|-----|-----|
| CRON_SECRET | mybot_cron_a8f3k2j9 |
| DATABASE_URL | Neon connection string |
| LINE_CHANNEL_SECRET | LINE Dev Console |
| LINE_CHANNEL_ACCESS_TOKEN | LINE Dev Console |
| GROQ_API_KEY | console.groq.com |
| GEMINI_API_KEY | aistudio.google.com |

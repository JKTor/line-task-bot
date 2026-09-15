# LINE Task Bot

> **TL;DR (EN):** A Thai-language task & expense bot on LINE. Natural Thai text in, structured records out —
> with a rule-based parser first and an LLM only as fallback, so ~90% of messages never touch an AI call.

พิมพ์เข้าไลน์ว่า **"พรุ่งนี้ส่งการบ้าน 4 โมง"** แล้วบอทแยกวัน เวลา และเรื่องออกมาเป็นงานในฐานข้อมูล
พร้อมเตือนตามเวลา — ใช้งานจริงทุกวัน ไม่ใช่เดโม

🔗 **Live:** https://line-task-bot-u5vn.onrender.com *(Render free tier — เครื่องหลับ ตื่นช้า ~1 นาทีในการเรียกครั้งแรก)*

---

## ทำอะไรได้

- **จดงานจากภาษาไทยธรรมชาติ** — "พรุ่งนี้บ่าย 3", "ศุกร์หน้า", "อีก 2 อาทิตย์", "สิ้นเดือน" แยกออกหมด
- **เตือนตามเวลา** + สรุปรายสัปดาห์ + เคารพ quiet hours (ไม่ทักตอนตี 2)
- **บันทึกรายรับ-รายจ่าย** ในแชทเดียวกัน
- **เว็บ dashboard** ล็อกอินด้วย LINE Login (OAuth + JWT cookie)
- **JSON API** ให้เครื่องมืออื่นเขียนแผนเข้ามาได้ — ผมใช้เขียนตารางงานจาก Claude Code บนเครื่องตัวเอง

## จุดที่ตัดสินใจเชิงวิศวกรรม

**1. กฎมาก่อน AI มาทีหลัง**
ข้อความส่วนใหญ่จบที่ชั้น regex (`parser.py` + `handlers/strict.py`) ไม่เรียก LLM เลย
AI (Gemini/Groq) เป็น fallback ชั้นสองเฉพาะประโยคที่กฎจับไม่ได้
→ เร็วกว่า ถูกกว่า และ**ผลลัพธ์เดิมทุกครั้งสำหรับ input เดิม** ซึ่งสำคัญกว่าความฉลาดเมื่อเป็นเรื่องวันนัดหมาย

**2. ทิศทางการ import เป็นทางเดียว**
`router → strict/ai_dispatch → tasks → routines → formatting → constants`
ตอนแรกเป็นไฟล์เดียว 1,133 บรรทัด แก้ทีไรพังที่อื่นทุกที จึงแยกเป็นแพ็กเกจและ**ล็อกทิศทางพึ่งพา**
ไม่ให้มี import ย้อนกลับ

**3. ถามกลับเมื่อไม่แน่ใจ แทนที่จะเดา**
ประโยคกำกวมจะเข้าสถานะ clarify แล้วถามกลับ พร้อม log ข้อความที่อ่านไม่ออกไว้ปรับกฎรอบหน้า
— ลงวันผิดแย่กว่าถามซ้ำ

**4. เตือนด้วย cron ภายนอก ไม่ใช่ background thread**
Render free tier หลับเมื่อไม่มี traffic → thread ในแอปตายเงียบ
จึงยิง `/cron/check` จากข้างนอกด้วย `CRON_SECRET` แทน (ยอมรับข้อจำกัดของ infra แทนที่จะสู้กับมัน)

## Stack

FastAPI · PostgreSQL (SQLAlchemy) · LINE Messaging API + LINE Login · Jinja2 · Gemini/Groq (fallback)
Deploy บน Render — push `main` = deploy อัตโนมัติ · Python ~5,000 บรรทัด

```
app/
├── main.py         FastAPI: webhook, dashboard, /cron/check
├── handlers/       logic ตอบข้อความทั้งหมด (router คือทางเข้า)
├── parser.py       แยกวันเวลาไทยด้วย regex  ← ตัวหลัก
├── ai_parser.py    fallback ผ่าน LLM         ← ชั้นสอง
├── scheduler.py    quiet hours (รองรับช่วงข้ามเที่ยงคืน)
├── auth.py         LINE Login OAuth + JWT
└── api.py          JSON API สำหรับเครื่องมือภายนอก
```

## เทสต์

สคริปต์ใน `scripts/` รันตรงๆ (ไม่ใช้ pytest) — ครอบคลุม parser ภาษาไทย, สถานะ clarify,
weekly summary guard และ `/api/*` 35 เคสผ่าน TestClient

```powershell
venv\Scripts\python.exe scripts\test_parser_th.py
venv\Scripts\python.exe scripts\test_api.py
```

## รัน local

```powershell
cp .env.example .env     # ใส่คีย์ LINE / DATABASE_URL / CRON_SECRET
venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

## ข้อจำกัดที่รู้ตัว

- Render free tier หลับ → เรียกครั้งแรกของวันรอ ~60 วินาที (เป็นพฤติกรรมปกติ ไม่ใช่บั๊ก)
- parser ครอบคลุมรูปแบบวันเวลาไทยที่ใช้บ่อย ไม่ได้ครบทุกแบบ — แบบที่จับไม่ได้ถูก log ไว้ทยอยเก็บ
- ยังไม่มี test runner มาตรฐาน (pytest) — เป็นสคริปต์รันมือ

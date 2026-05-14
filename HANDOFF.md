# LINE Task Bot — Handoff

โปรเจกต์: LINE chatbot จัดการงาน + เตือน deadline สำหรับใช้ส่วนตัว

---

## 🚨 สถานะปัจจุบัน (มีปัญหา — อ่านด่วน)

**บอทตอบ "เกิดข้อผิดพลาด"** ทุกครั้งที่ใช้ฟีเจอร์ที่ต้องใช้ DB  
**Root cause:** PostgreSQL (Neon) ล้มเหลวด้วย error:
```
psycopg2.OperationalError: invalid sslmode value: "requ"
```

---

## ✅ งานที่เสร็จแล้ว (session 2026-05-15)

1. เพิ่ม 4 ฟีเจอร์ใหม่:
   - Morning Digest (`/cron/morning`) — แจ้งเตือน 8 โมงเช้า
   - Weekly Summary (`/cron/weekly`) — สรุปรายสัปดาห์อาทิตย์
   - Routine System — กิจวัตรประจำวันพร้อมแจ้งเตือนล่วงหน้า
   - CHANGELOG.md
2. แก้ DATETIME → TIMESTAMP สำหรับ PostgreSQL migration
3. เพิ่ม NullPool + SSL connect_args fix
4. เพิ่ม `/test/db` endpoint (ชั่วคราว) และ DB diagnostics ใน `/debug/ai`

---

## ❌ ปัญหาที่ยังไม่แก้

**error: `invalid sslmode value: "requ"`**
- เกิดกับทุก DB operation
- ลอง NullPool, connect_args, URL stripping แล้ว ยังไม่หาย
- Render อาจ deploy ช้าหรือมี build error

**Latest commits (top = newest):**
```
91e87f5  debug: add DB URL diagnostics to /debug/ai
6db88c8  fix: strip sslmode from URL + connect_args
de9a8ba  fix: use NullPool for Neon
8882c4e  fix: use FastAPI Depends(get_db) in test/db
82fac04  test: add /test/db endpoint
e71c743  fix: TIMESTAMP instead of DATETIME
4392688  feat: morning digest, weekly summary, routines
```

---

## 🔧 ขั้นถัดไป (ต้องทำก่อน)

### 1. ตรวจ Neon DB (แนะนำสุด)
- ล็อกอิน **neon.tech**
- ตรวจว่า DB ยังใช้งานได้ (free tier หมดอายุมั้ย?)
- Copy connection string ใหม่ → ใส่ใน Render ENV → `DATABASE_URL`

### 2. ตรวจ Render Deploy Logs
- เข้า **dashboard.render.com** → line-task-bot → Logs
- หา error ตอน startup
- ถ้า deploy ไม่เสร็จ → trigger manual deploy

### 3. ตรวจสอบผ่าน /debug/ai
หลัง deploy เสร็จ เรียก:
```
GET https://line-task-bot-u5vn.onrender.com/debug/ai
```
ถ้า response มี `db_scheme`, `db_host` → code ใหม่ทำงานแล้ว

### 4. ทดสอบ DB
```
GET https://line-task-bot-u5vn.onrender.com/test/db
```
ต้องได้ `{"overall": "pass"}`

---

## ✅ เมื่อ DB ใช้งานได้แล้ว

1. ทดสอบ morning digest: `GET /cron/morning?secret=mybot_cron_a8f3k2j9`
2. พิมพ์ "ออกกำลังกายทุกวัน 18.00" ใน LINE → ต้องตอบยืนยัน
3. ลบ `/test/db` endpoint ออกจาก `app/main.py` → push ครั้งสุดท้าย
4. ตั้ง cron-job.org เพิ่ม 2 อัน:
   - `/cron/morning?secret=mybot_cron_a8f3k2j9` → ทุกวัน 01:00 UTC
   - `/cron/weekly?secret=mybot_cron_a8f3k2j9` → ทุกอาทิตย์ 01:00 UTC

---

## Live URL
https://line-task-bot-u5vn.onrender.com

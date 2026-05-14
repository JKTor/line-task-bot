# Changelog

บันทึกการเปลี่ยนแปลงทั้งหมดของ LINE Task Bot

---

## [2026-05-15] — Session 3: QA + Bug fixes ครบระบบ

### แก้ Bug (Critical)
- **`check_routine_reminders` crash** ถ้า time_hour > 23: เพิ่ม clamp + try/except ต่อ routine
- **Midnight-crossing routine ไม่ส่ง**: routine ตี 1 advance 30 นาที ไม่เคยได้แจ้งเตือน — แก้โดย detect ว่า routine time ผ่านแล้วให้ใช้พรุ่งนี้แทน
- **`_mark_done` ซ้ำ**: mark done งานที่เสร็จแล้ว spawn recurring อีกรอบ — เพิ่ม early return

### แก้ Bug (Medium)
- **`_recurring_label` / `_next_recurring_deadline` crash**: "weekly:abc" → try/except ป้องกัน ValueError
- **`_add_routine` clamp**: clamp time_hour/minute/advance ก่อน save ไม่ให้ค่าผิดเข้า DB

### เพิ่มฟีเจอร์
- **`ลบกิจวัตรทั้งหมด`**: handler ใหม่ทั้ง strict parser และ AI intent
- **Morning digest แสดง routine**: เพิ่มรายการ routine ของวันในข้อความเช้า
- **Notify str "(วันก่อน)"**: แสดงหมายเหตุถ้าแจ้งเตือนข้ามคืน

### ปรับปรุง AI Prompt
- ชี้แจดความแตกต่าง routine vs recurring task ให้ชัดขึ้น (กิจวัตร = นิสัย ไม่ต้อง done; งานซ้ำ = มี deadline ต้อง done)
- เพิ่ม examples ที่ชัดเจนกว่าเดิม
- เพิ่ม delete_all_routines intent

### ไฟล์ที่แก้ไข
- `app/line_handler.py` — mark_done check, delete_all_routines, clamp, try/except
- `app/scheduler.py` — midnight fix, clamp, morning digest + routines
- `app/ai_parser.py` — prompt rewrite สำหรับ routine/recurring distinction

---

## [2026-05-15] — Session 2: แก้ SSL bug + Routine ใช้งานได้

### แก้ Bug
- **SSL error `invalid sslmode value: "requ"`**: ค่า `sslmode` ใน `DATABASE_URL` ถูกตัดให้สั้น psycopg2 อ่านไม่ได้ แก้โดยดึง `sslmode` ออกจาก URL แล้วส่งผ่าน `connect_args` แทน (normalize ค่าผิดเป็น `require` อัตโนมัติ)
- **AI ส่ง routine เป็น non-dict**: เพิ่ม `isinstance()` check ป้องกัน crash ถ้า AI ส่ง `"routine"` เป็น string แทน dict

### ไฟล์ที่แก้ไข
- `app/database.py` — strip sslmode จาก URL + normalize + pass via connect_args
- `app/line_handler.py` — isinstance guard สำหรับ routine/tasks จาก AI

---

## [2026-05-15] — Session: เพิ่มฟีเจอร์แจ้งเตือนและกิจวัตร

### เพิ่มใหม่
- **Morning Digest** (`/cron/morning`): แจ้งเตือนตอน 8 โมงเช้า รายการงานวันนี้และงานที่เลยกำหนด พร้อม format สวยงาม
- **Weekly Summary** (`/cron/weekly`): สรุปรายสัปดาห์ทุกวันอาทิตย์ — งานที่เสร็จ/เลยกำหนด/สัปดาห์หน้า
- **Routine (กิจวัตรประจำวัน)**: บันทึกกิจกรรมประจำวันและรับแจ้งเตือนก่อนเวลา
  - เพิ่มกิจวัตรด้วยภาษาธรรมชาติ เช่น "ออกกำลังกายทุกวัน 18.00"
  - พิมพ์ "กิจวัตร" เพื่อดูรายการ
  - พิมพ์ "ลบกิจวัตร <id>" เพื่อลบ
  - รองรับทุกวัน หรือเฉพาะวันในสัปดาห์
- **`Task.completed_at`**: บันทึกเวลาที่ mark งานเสร็จ (ใช้สำหรับ weekly summary)
- **`migrate_db()`**: safe schema migration สำหรับ existing deployments

### เปลี่ยนแปลง
- **`/cron/check`**: เพิ่มการตรวจสอบ routine reminders ในรอบเดียวกัน
- **`_mark_done` / `_done_all`**: set `completed_at` เมื่อ mark งานเสร็จ
- **`HELP_TEXT`**: อัปเดตให้แสดงคำสั่งกิจวัตร

### ไฟล์ที่แก้ไข
- `app/models.py` — เพิ่ม `completed_at` ใน Task + สร้าง `Routine` model
- `app/database.py` — เพิ่ม `migrate_db()` + เก็บ retry logic จาก remote
- `app/line_handler.py` — เพิ่ม routine CRUD handlers + อัปเดต strict parser
- `app/ai_parser.py` — เพิ่ม routine intents ใน system prompt
- `app/scheduler.py` — เพิ่ม `morning_digest`, `weekly_summary`, `check_routine_reminders`
- `app/main.py` — เพิ่ม endpoints `/cron/morning` และ `/cron/weekly`

### cron-job.org ที่ต้องตั้งเพิ่ม
| Endpoint | Schedule (UTC) | เวลาไทย |
|----------|---------------|---------|
| `/cron/morning?secret=...` | ทุกวัน 01:00 | 8 โมงเช้า |
| `/cron/weekly?secret=...` | ทุกอาทิตย์ 01:00 | อาทิตย์ 8 โมง |

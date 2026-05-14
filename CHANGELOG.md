# Changelog

บันทึกการเปลี่ยนแปลงทั้งหมดของ LINE Task Bot

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

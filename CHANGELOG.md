# Changelog

บันทึกการเปลี่ยนแปลงทั้งหมดของ LINE Task Bot

---

## [2026-09-11] — แยก `line_handler.py` (1,133 บรรทัด) เป็นแพ็กเกจ `app/handlers/`

**เหตุผล:** ไฟล์เดียวโตจนหาของไม่เจอ — คำสั่งงาน กิจวัตร เงิน สถานะถามกลับ ตัวจับ pattern
และตัวแปลผลจาก AI อยู่ปนกันหมด แก้ทีต้องเลื่อนหาทั้งไฟล์

**โครงใหม่** (ไฟล์ใหญ่สุดเหลือ 303 บรรทัด):

```
app/handlers/
  router.py        59   ทางเข้า — ตัดสินว่าส่งข้อความไปชั้นไหน  <- เริ่มอ่านที่นี่
    strict.py      152  ชั้น 1 จับ pattern (ข้อความส่วนใหญ่จบตรงนี้ ไม่เรียก AI)
    ai_dispatch.py 278  ชั้น 2 แปลง intent จาก AI เป็นการกระทำ
  tasks.py         303  งาน — เพิ่ม/ดู/ปิด/เลื่อน/ลบ
  routines.py      112  กิจวัตรประจำวัน
  money.py         128  รายรับ-รายจ่าย (+ _delete_smart จุดที่ id งานกับเงินชนกัน)
  clarify.py        73  สถานะถามกลับ + log ข้อความที่อ่านไม่ออก
  formatting.py    116  แปลงข้อมูลเป็นข้อความ + คำนวณวันเวลา (ไม่แตะ DB)
  constants.py      41  ข้อความคงที่
```

ทั้งสองชั้น (pattern / AI) เรียกโค้ดทำงานชุดเดียวกัน — AI เปลี่ยนได้แค่ *การตีความ*
ไม่ได้เปลี่ยน *วิธีทำ* · ทิศทาง import เป็นทางเดียวเสมอ ไม่มี import วนกลับ

**วิธีย้าย และวิธีตรวจว่าไม่พัง:**
- ไม่พิมพ์โค้ดใหม่เลย — ใช้สคริปต์ตัดทีละบล็อกตามเลขบรรทัดไปวางไฟล์ใหม่ แก้แค่ import ข้ามไฟล์
- เทียบ AST ของทุกฟังก์ชันกับของเดิมใน git → **เหมือนกันเป๊ะ 70/70 ตัว** (ต่าง 0 หาย 0)
- ชุดเทสต์เดิม 8 ไฟล์ผ่านหมด **โดยไม่ต้องแก้เทสต์สักบรรทัด**
  (`test_api` 42 เคส, `test_config` 7 เคส, ที่เหลือ ALL PASS)

**ของเดิมไม่พัง:** `app/line_handler.py` เหลือเป็นหน้ากาก 81 บรรทัดที่ re-export ชื่อเดิมครบ 70 ตัว
โค้ดและสคริปต์เก่าที่ `import app.line_handler` ยังทำงานเหมือนเดิม —
โค้ดใหม่ให้ import จาก `app.handlers` ส่วน `main.py` ชี้ไปที่อยู่ใหม่ตรงๆ แล้ว

---

## [2026-08-12b] — แก้ "ลบรายจ่ายแล้วยอดยังรวมอยู่"

**อาการ:** ผู้ใช้พิมพ์ `ลบ 3` เพื่อลบรายจ่าย บอทตอบ "🗑️ ลบแล้ว: #3" แต่สรุปยอดยังรวมรายการนั้น
**ต้นเหตุ:** `tasks` กับ `expenses` นับ id คนละชุด เลขจึงซ้ำกันได้ — `ลบ <id>` วิ่งเข้า `_delete_task` เสมอ
→ ลบ **งาน** #3 ทิ้งเงียบๆ (ข้อมูลหาย!) แล้วตอบว่าลบสำเร็จ ส่วนรายจ่าย #3 ยังอยู่ครบ
**แก้:** `_delete_smart()` — ดูทั้งสองตารางก่อนตัดสินใจ
- มีทั้งงานและรายการเงินเลขนั้น → **ถามก่อน ไม่เดา** (แสดงทั้งคู่ + บอกให้พิมพ์ `ลบงาน N` / `ลบรายจ่าย N`)
- มีแต่รายการเงิน → ลบรายการเงินให้เลย (ตรงกับที่ผู้ใช้ตั้งใจ)
- มีแต่งาน → ลบงานเหมือนเดิม
- เพิ่มคำสั่ง `ลบงาน <id>` (ระบุชัด), quick reply ของงานเปลี่ยนไปส่ง `ลบงาน <id>` แทน `ลบ <id>`
- ข้อความตอบตอนลบงานบอกชื่องานด้วย (`🗑️ ลบงานแล้ว: #3 ส่งรายงาน`) จะได้เห็นทันทีว่าลบผิดตัว
- AI intent `delete` ใช้ `_delete_smart` เหมือนกัน
- เทสใหม่ใน `scripts/test_expense.py`: จำลอง id ชนกันจริง ครอบทั้ง 3 ทาง

---

## [2026-08-12] — รายรับ-รายจ่าย: พิมพ์ "กาแฟ 60" ในไลน์แล้วบันทึกเลย

### เพิ่มฟีเจอร์
- **ตาราง `expenses`** (`models.Expense`) — title / amount / kind (expense|income) / category / spent_at (UTC-naive) — สร้างอัตโนมัติโดย `create_all`
- **`app/expense.py`** — regex parser + เดาหมวดจากคำไทย (8 หมวด) + สรุปยอด/ฟอร์แมตข้อความ
  - รับได้: `กาแฟ 60`, `กาแฟ60`, `กาแฟ 60 บาท`, `ค่าไฟ 1,250`, `จ่ายค่าไฟ 800`, `ซื้อรองเท้า 1200`, `-60 กาแฟ`, `+500 ค่าขนม`, `รับ เงินเดือน 15000`, `เมื่อวาน กาแฟ 60`
  - **ไม่แตะข้อความงาน**: `ประชุม 3 โมง`, `ประชุม 15.30`, `เสร็จ 3`, `ลบ 2`, `เตือนจ่ายค่าไฟ 800`, `พรุ่งนี้จ่ายค่าเน็ต 599` ยังเป็นงานเหมือนเดิม
- **คำสั่งใหม่ใน LINE:** `สรุป` (สรุปเดือนนี้แยกหมวด + กราฟแท่ง + เฉลี่ยต่อวัน), `รายจ่ายวันนี้` / `รายจ่ายเมื่อวาน`, `ลบรายจ่าย <id>`, `รายจ่าย/รายรับ <ของ> <ราคา>` — พร้อม quick reply หลังบันทึก
- **AI intents ใหม่:** `expense` / `expense_summary` / `expense_list` / `expense_delete` — จับประโยคยาว เช่น "เมื่อวานกินข้าว 60 กับกาแฟ 45" และแยก "จ่ายแล้ว" (เงิน) ออกจาก "พรุ่งนี้ต้องจ่าย" (งาน)
- **หน้าเว็บ `/dashboard/expenses`** — เลือกเดือนย้อนหลัง, การ์ดยอดรับ/จ่าย/คงเหลือ, แถบสัดส่วนรายหมวด, ลบรายการได้ (ownership-checked) + ลิงก์ "💸 เงิน" ในเมนูทุกหน้า

### หมายเหตุทางเทคนิค
- `_try_strict` เรียกคำสั่งเงิน **ก่อน** คำสั่งงาน (ไม่งั้น `ลบรายจ่าย 3` จะไปชนกับ `ลบ <id>`) และเรียกตัวบันทึกเงิน **ท้ายสุด** (ถ้าไม่ใช่คำสั่งงานอะไรเลยค่อยอ่านเป็นเงิน)
- `parse_expense` ตั้งใจให้ขี้ระแวง — ไม่มั่นใจคืน `None` ปล่อยให้ pipeline งานเดิมทำงานต่อ
- ⚠️ ตัวเลขทศนิยมที่หน้าตาเหมือนเวลา (`20.50`) ถือเป็นเวลา ต้องพิมพ์ `20.50 บาท` ถึงจะนับเป็นเงิน
- ทดสอบ: `scripts/test_expense.py` — 57 เคส (parser + flow ผ่าน `handle_command` + หน้าเว็บผ่าน TestClient + ownership)

### แก้ Bug
- **หน้าเว็บทุกหน้าจะ 500 บน starlette เวอร์ชันใหม่**: `TemplateResponse("name.html", {...})` ถูกถอดออกใน starlette 1.0 — เปลี่ยนทั้ง 6 หน้าเป็น `TemplateResponse(request, "name.html", {...})` ซึ่ง starlette 0.38 (เวอร์ชันบน prod) รองรับอยู่แล้ว
- เพิ่ม `scripts/test_web_pages.py` — render ทุกหน้าจริงผ่าน TestClient + เช็คสิทธิ์เข้าถึง กันพลาดซ้ำ

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

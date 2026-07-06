# คู่มือส่งมอบ / เปิดใช้งาน LINE Task Bot

เอกสารนี้แบ่งชัดว่า **ลูกค้าต้องทำอะไรเอง** vs **ผู้พัฒนา (dev) ทำให้**
ใช้เป็นเช็คลิสต์ตอนรับงานฟรีแลนซ์หรือส่งมอบระบบ

---

## 🙋 ส่วนที่ลูกค้าต้องทำเอง (ผูกกับตัวตน/บัญชี/เงินของลูกค้า — dev ทำแทนไม่ได้)

| # | สิ่งที่ต้องทำ | ทำที่ไหน | ได้อะไรมา |
|---|--------------|----------|-----------|
| 1 | สร้าง **LINE Official Account + Messaging API channel** | developers.line.biz | `LINE_CHANNEL_SECRET`, `LINE_CHANNEL_ACCESS_TOKEN` |
| 2 | สร้าง **LINE Login channel** (คนละตัวกับข้อ 1) | developers.line.biz | `LINE_LOGIN_CLIENT_ID`, `LINE_LOGIN_SECRET` |
| 3 | ปิด auto-reply เดิมของ OA | manager.line.biz | (ไม่งั้นบอทกับ auto-reply ตอบชนกัน) |
| 4 | เปิดบัญชี **hosting** (Render) + Postgres | render.com | `DATABASE_URL` (Postgres) |
| 5 | สมัคร **Groq / Gemini API key** (บัญชี+โควตาของลูกค้า) | console.groq.com / ai.google.dev | `GROQ_API_KEY`, `GEMINI_API_KEY` |
| 6 | เตรียม **PromptPay / ช่องทางรับเงิน** (ถ้าจะเก็บเงินผู้ใช้ปลายทาง) | ธนาคารของลูกค้า | — |

> 💡 ทางที่ลื่นที่สุด: ลูกค้าสมัครบัญชีข้างบน แล้ว**เชิญ dev เป็น admin / แชร์ credential**
> ให้ dev ตั้งค่าที่เหลือทั้งหมด ลูกค้าแตะจริง ๆ แค่ข้อ 1–5

---

## 🧑‍💻 ส่วนที่ dev ทำให้ (งานเทคนิคทั้งหมด)

1. Deploy โค้ดขึ้น Render (repo + `render.yaml` + `Procfile` มีให้แล้ว)
2. ตั้งค่า **ENV ทั้งหมด** ตาม `.env.example` บน Render dashboard
   - ⚠️ `DATABASE_URL` ต้องเป็น **Postgres** — ถ้าเป็น SQLite ข้อมูลหายทุก redeploy
   - `JWT_SECRET` = `openssl rand -hex 32`, `ADMIN_SECRET`/`CRON_SECRET` = random
   - `APP_BASE_URL` = URL จริงของ Render (ต้อง https เพื่อให้ cookie Secure ทำงาน)
3. ตั้ง **LINE Login callback URL** = `https://<APP_BASE_URL>/auth/callback`, scope `profile openid`
4. ตั้ง **Messaging API webhook URL** = `https://<APP_BASE_URL>/webhook` + เปิด "Use webhook"
5. ตั้ง **cron-job.org** 4 งาน: `/health`, `/cron/check`, `/cron/morning`, `/cron/weekly`
   (ใส่ `?secret=<CRON_SECRET>` ใน 3 อันหลัง) — ดู HANDOFF.md
6. ทดสอบครบ (ดู checklist ด้านล่าง) แล้วส่งมอบ

---

## ✅ Checklist ทดสอบก่อนส่งมอบ

- [ ] `GET /health` → `{"status":"ok"}`
- [ ] `GET /debug/ai?secret=<ADMIN_SECRET>` → key ครบทุกตัวเป็น `true`
- [ ] พิมพ์ใน LINE: `เพิ่ม ส่งรายงาน พรุ่งนี้ 18:00` → บอทตอบ + มีปุ่ม quick reply
- [ ] กดปุ่ม `✅ เสร็จ` / `🗑️ ลบ` → ทำงานถูกต้อง
- [ ] `เข้าสู่ระบบเว็บ` (`/auth/line`) → ล็อกอิน LINE สำเร็จ เห็น `/dashboard`
- [ ] เพิ่ม task แล้ว **redeploy** → task ยังอยู่ (ยืนยัน Postgres ไม่ใช่ SQLite)
- [ ] `/admin?secret=<ADMIN_SECRET>` → เห็นรายชื่อ user + activate plan ได้
- [ ] reminder ยิงจริง (รอ `/cron/check` หรือ trigger เอง)

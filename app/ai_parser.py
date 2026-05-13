"""Translate free-form Thai messages into structured intents.

Tries providers in order:
  1. Groq (free, no region restriction) — preferred
  2. Google Gemini (if GROQ unavailable in some region)
"""
import json
import os
from datetime import datetime
from typing import Any, Dict

import pytz

TZ = pytz.timezone("Asia/Bangkok")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

SYSTEM_PROMPT = """คุณคือผู้ช่วยแปลงข้อความภาษาไทย/อังกฤษ ให้เป็น JSON สำหรับจัดการ to-do list
ตอบเป็น JSON อย่างเดียว ห้ามมี markdown หรือ code fence

Schema:
{
  "intent": "add" | "list_today" | "list_all" | "done" | "delete" | "delete_all" | "done_all" | "cancel_recurring" | "help" | "unknown",
  "tasks": [{"title": "string", "deadline": "YYYY-MM-DD HH:MM" or null, "recurring": "daily"|"weekly:N"|"monthly:D"|null}],
  "task_id": integer or null,
  "reply": "ข้อความตอบกลับสั้นๆ เป็นมิตร (optional)"
}

กฎทั่วไป:
- ถ้าผู้ใช้สั่งเพิ่มงานหลายอย่าง ให้ list หลายตัวใน tasks
- ถ้าไม่ระบุเวลา ให้ deadline = null
- ถ้าระบุแค่วันไม่ระบุเวลา ใช้ 23:59
- ถ้าผู้ใช้พิมพ์งงๆ จับใจความไม่ได้ → intent="unknown"
- intent="done"/"delete"/"cancel_recurring" ต้องมี task_id

กฎงานซ้ำ (recurring):
- "ทุกวัน" / "every day" / "daily" → recurring="daily"
- "ทุกจันทร์" / "every monday" → recurring="weekly:0"
- "ทุกอังคาร" → recurring="weekly:1"
- "ทุกพุธ" → recurring="weekly:2"
- "ทุกพฤหัส" → recurring="weekly:3"
- "ทุกศุกร์" → recurring="weekly:4"
- "ทุกเสาร์" → recurring="weekly:5"
- "ทุกอาทิตย์" → recurring="weekly:6"
- "ทุกสัปดาห์" (ไม่ระบุวัน) → recurring="weekly:0" (จันทร์ default)
- "ทุกวันที่ 15" → recurring="monthly:15"
- "ทุกเดือน" (ไม่ระบุวันที่) → recurring="monthly:1"
- deadline ของงานซ้ำ = ครั้งแรกที่จะเกิดขึ้น
- "ยกเลิกซ้ำ 3" / "หยุดซ้ำงาน 3" → intent="cancel_recurring", task_id=3

⚠️ การแปลงเวลาภาษาไทย (ใช้เป๊ะตามนี้):
- "ตี 1" = 01:00, "ตี 2" = 02:00, "ตี 3" = 03:00, "ตี 4" = 04:00, "ตี 5" = 05:00
- "6 โมงเช้า" = 06:00, "7 โมงเช้า" = 07:00, ... "11 โมงเช้า" = 11:00
- "เช้า" (เฉยๆ) = 09:00, "สาย" = 10:00
- "เที่ยง" / "เที่ยงวัน" = 12:00
- "บ่ายโมง" / "บ่าย 1" = 13:00, "บ่าย 2" = 14:00, "บ่าย 3" = 15:00
- "4 โมงเย็น" / "บ่าย 4" = 16:00, "5 โมงเย็น" = 17:00, "6 โมงเย็น" = 18:00
- "เย็น" (เฉยๆ) = 18:00
- "1 ทุ่ม" = 19:00, "2 ทุ่ม" = 20:00, "3 ทุ่ม" = 21:00, "4 ทุ่ม" = 22:00, "5 ทุ่ม" = 23:00 ⚠️ ทุ่ม ≠ โมงเย็น
- "ค่ำ" = 20:00, "ดึก" = 23:00
- "เที่ยงคืน" = 00:00

ตัวอย่าง:
"พรุ่งนี้ส่งรายงาน 6 โมงเย็น" → {"intent":"add","tasks":[{"title":"ส่งรายงาน","deadline":"<พรุ่งนี้> 18:00","recurring":null}]}
"อ่านหนังสือ 4 ทุ่ม" → {"intent":"add","tasks":[{"title":"อ่านหนังสือ","deadline":"<วันนี้> 22:00","recurring":null}]}
"ออกกำลังกายทุกวัน 6 โมงเช้า" → {"intent":"add","tasks":[{"title":"ออกกำลังกาย","deadline":"<พรุ่งนี้> 06:00","recurring":"daily"}]}
"ทุกจันทร์ประชุมทีม 9 โมงเช้า" → {"intent":"add","tasks":[{"title":"ประชุมทีม","deadline":"<จันทร์หน้า> 09:00","recurring":"weekly:0"}]}
"วันนี้มีอะไรบ้าง" → {"intent":"list_today"}
"งานทั้งหมด" → {"intent":"list_all"}
"งาน 3 เสร็จแล้ว" → {"intent":"done","task_id":3}
"ลบงานที่ 2" → {"intent":"delete","task_id":2}
"ลบทั้งหมด" / "ลบงานทั้งหมด" → {"intent":"delete_all"}
"เคลียร์งานหมดเลย" → {"intent":"delete_all"}
"ปิดงานทั้งหมด" / "เสร็จหมดแล้ว" → {"intent":"done_all"}
"ยกเลิกซ้ำงาน 3" → {"intent":"cancel_recurring","task_id":3}
"ช่วยอะไรได้บ้าง" → {"intent":"help"}
"""


def is_enabled() -> bool:
    return bool(GROQ_API_KEY or GEMINI_API_KEY)


def _strip_json_fence(s: str) -> str:
    s = (s or "").strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        if s.endswith("```"):
            s = s[: -3]
    return s.strip()


def _build_user_prompt(text: str) -> str:
    now = datetime.now(TZ)
    return (
        f"ปัจจุบัน: {now.strftime('%A %Y-%m-%d %H:%M')} (Asia/Bangkok)\n"
        f"ข้อความผู้ใช้: {text}\n\n"
        f"ตอบเป็น JSON เท่านั้น:"
    )


def _try_groq(text: str):
    """Return parsed dict on any successful model call, else None on total failure."""
    from groq import Groq

    client = Groq(api_key=GROQ_API_KEY)
    models = ("llama-3.3-70b-versatile", "llama-3.1-8b-instant", "gemma2-9b-it")
    for model_name in models:
        try:
            print(f"[ai_parser/groq] trying {model_name}")
            resp = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": _build_user_prompt(text)},
                ],
                temperature=0.2,
                response_format={"type": "json_object"},
            )
            raw = _strip_json_fence(resp.choices[0].message.content or "")
            data = json.loads(raw)
            if not isinstance(data, dict) or "intent" not in data:
                continue
            print(f"[ai_parser/groq] success with {model_name}")
            return data
        except Exception as e:
            print(f"[ai_parser/groq] {model_name} failed: {type(e).__name__}: {str(e)[:150]}")
            continue
    print("[ai_parser/groq] all groq models failed")
    return None


def _try_gemini(text: str):
    """Return parsed dict on any successful model call, else None on total failure."""
    import google.generativeai as genai

    genai.configure(api_key=GEMINI_API_KEY)
    models = ("gemini-2.0-flash-lite", "gemini-2.5-flash-lite", "gemini-2.5-flash")
    for model_name in models:
        try:
            print(f"[ai_parser/gemini] trying {model_name}")
            model = genai.GenerativeModel(
                model_name=model_name,
                generation_config={"temperature": 0.2},
            )
            resp = model.generate_content(SYSTEM_PROMPT + "\n\n" + _build_user_prompt(text))
            raw = _strip_json_fence(getattr(resp, "text", "") or "")
            data = json.loads(raw)
            if not isinstance(data, dict) or "intent" not in data:
                continue
            print(f"[ai_parser/gemini] success with {model_name}")
            return data
        except Exception as e:
            print(f"[ai_parser/gemini] {model_name} failed: {type(e).__name__}: {str(e)[:150]}")
            continue
    print("[ai_parser/gemini] all gemini models failed")
    return None


def parse(text: str) -> Dict[str, Any]:
    """Return parsed intent dict. Tries Groq first, then Gemini.
    Falls through to next provider only if the current one totally failed (None)."""
    if GROQ_API_KEY:
        result = _try_groq(text)
        if result is not None:
            return result

    if GEMINI_API_KEY:
        result = _try_gemini(text)
        if result is not None:
            return result

    return {"intent": "unknown", "reply": "AI ไม่พร้อมใช้งานชั่วคราว"}

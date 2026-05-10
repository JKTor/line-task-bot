"""Use Gemini to translate free-form Thai messages into structured intents
that the existing handler can dispatch."""
import json
import os
from datetime import datetime
from typing import Any, Dict

import google.generativeai as genai
import pytz

TZ = pytz.timezone("Asia/Bangkok")

_API_KEY = os.getenv("GEMINI_API_KEY", "")
if _API_KEY:
    genai.configure(api_key=_API_KEY)

SYSTEM_PROMPT = """คุณคือผู้ช่วยแปลงข้อความภาษาไทย/อังกฤษ ให้เป็น JSON สำหรับจัดการ to-do list
ตอบเป็น JSON อย่างเดียว ห้ามมี markdown หรือ code fence

Schema:
{
  "intent": "add" | "list_today" | "list_all" | "done" | "delete" | "help" | "unknown",
  "tasks": [{"title": "string", "deadline": "YYYY-MM-DD HH:MM" or null}],
  "task_id": integer or null,
  "reply": "ข้อความตอบกลับสั้นๆ เป็นมิตร (optional)"
}

กฎ:
- ถ้าผู้ใช้สั่งเพิ่มงานหลายอย่าง ให้ list หลายตัวใน tasks
- ถ้าไม่ระบุเวลา ให้ deadline = null
- ถ้าระบุแค่วันไม่ระบุเวลา ใช้ 23:59
- "เช้า"=09:00, "สาย"=10:00, "เที่ยง"=12:00, "บ่าย N"=12+N, "เย็น"=18:00, "ค่ำ"=20:00, "ดึก"=23:00
- ถ้าผู้ใช้พิมพ์งงๆ จับใจความไม่ได้ → intent="unknown"
- intent="done"/"delete" ต้องมี task_id

ตัวอย่าง:
"พรุ่งนี้ส่งรายงาน 6 โมงเย็น" → {"intent":"add","tasks":[{"title":"ส่งรายงาน","deadline":"<DATE+1> 18:00"}]}
"วันนี้มีอะไรบ้าง" → {"intent":"list_today"}
"งานทั้งหมด" → {"intent":"list_all"}
"งาน 3 เสร็จแล้ว" → {"intent":"done","task_id":3}
"ลบงานที่ 2" → {"intent":"delete","task_id":2}
"ช่วยอะไรได้บ้าง" → {"intent":"help"}
"""


def is_enabled() -> bool:
    return bool(_API_KEY)


def parse(text: str) -> Dict[str, Any]:
    """Return parsed intent dict. Falls back to {'intent':'unknown'} on any error."""
    if not _API_KEY:
        return {"intent": "unknown", "reply": "AI parser ยังไม่ได้ตั้งค่า GEMINI_API_KEY"}

    now = datetime.now(TZ)
    user_prompt = (
        f"ปัจจุบัน: {now.strftime('%A %Y-%m-%d %H:%M')} (Asia/Bangkok)\n"
        f"ข้อความ: {text}"
    )
    try:
        model = genai.GenerativeModel(
            model_name="gemini-2.0-flash",
            system_instruction=SYSTEM_PROMPT,
            generation_config={
                "response_mime_type": "application/json",
                "temperature": 0.2,
            },
        )
        resp = model.generate_content(user_prompt)
        data = json.loads(resp.text or "{}")
        if not isinstance(data, dict) or "intent" not in data:
            return {"intent": "unknown"}
        return data
    except Exception as e:
        print(f"[ai_parser] error: {e}")
        return {"intent": "unknown", "reply": "AI ขัดข้อง ลองใหม่อีกครั้ง"}

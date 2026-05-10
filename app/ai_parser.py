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


_MODEL_CANDIDATES = (
    "gemini-2.5-flash-lite",   # most generous free tier (1000 req/day)
    "gemini-2.0-flash-lite",   # 200 req/day
    "gemini-2.5-flash",        # 250 req/day
    "gemini-1.5-flash",        # legacy fallback
)


def _strip_json_fence(s: str) -> str:
    s = (s or "").strip()
    if s.startswith("```"):
        # remove ```json or ``` opening, and trailing ```
        s = s.split("\n", 1)[1] if "\n" in s else s
        if s.endswith("```"):
            s = s[: -3]
    return s.strip()


def parse(text: str) -> Dict[str, Any]:
    """Return parsed intent dict. Falls back to {'intent':'unknown'} on any error."""
    if not _API_KEY:
        return {"intent": "unknown", "reply": "AI parser ยังไม่ได้ตั้งค่า GEMINI_API_KEY"}

    now = datetime.now(TZ)
    user_prompt = (
        f"{SYSTEM_PROMPT}\n\n"
        f"ปัจจุบัน: {now.strftime('%A %Y-%m-%d %H:%M')} (Asia/Bangkok)\n"
        f"ข้อความผู้ใช้: {text}\n\n"
        f"ตอบเป็น JSON เท่านั้น:"
    )

    last_err = None
    for model_name in _MODEL_CANDIDATES:
        try:
            model = genai.GenerativeModel(
                model_name=model_name,
                generation_config={"temperature": 0.2},
            )
            resp = model.generate_content(user_prompt)
            raw = _strip_json_fence(getattr(resp, "text", "") or "")
            if not raw:
                last_err = "empty response"
                continue
            data = json.loads(raw)
            if not isinstance(data, dict) or "intent" not in data:
                last_err = f"bad shape: {raw[:200]}"
                continue
            return data
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            print(f"[ai_parser] {model_name} failed: {last_err}")
            continue

    print(f"[ai_parser] all models failed. last_err={last_err}")
    return {"intent": "unknown", "reply": f"AI ขัดข้อง: {last_err}"}

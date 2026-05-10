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
"พรุ่งนี้ส่งรายงาน 6 โมงเย็น" → {"intent":"add","tasks":[{"title":"ส่งรายงาน","deadline":"<วันพรุ่งนี้> 18:00"}]}
"วันนี้มีอะไรบ้าง" → {"intent":"list_today"}
"งานทั้งหมด" → {"intent":"list_all"}
"งาน 3 เสร็จแล้ว" → {"intent":"done","task_id":3}
"ลบงานที่ 2" → {"intent":"delete","task_id":2}
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


def _try_groq(text: str) -> Dict[str, Any]:
    from groq import Groq

    client = Groq(api_key=GROQ_API_KEY)
    models = ("llama-3.3-70b-versatile", "llama-3.1-8b-instant", "gemma2-9b-it")
    last_err = None
    last_model = None
    for model_name in models:
        last_model = model_name
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
                last_err = f"bad shape: {raw[:200]}"
                continue
            print(f"[ai_parser/groq] success with {model_name}")
            return data
        except Exception as e:
            last_err = f"{type(e).__name__}: {str(e)[:150]}"
            print(f"[ai_parser/groq] {model_name} failed: {last_err}")
            continue
    return {"intent": "unknown", "reply": f"AI ขัดข้อง (groq/{last_model}): {last_err[:200] if last_err else ''}"}


def _try_gemini(text: str) -> Dict[str, Any]:
    import google.generativeai as genai

    genai.configure(api_key=GEMINI_API_KEY)
    models = ("gemini-2.0-flash-lite", "gemini-2.5-flash-lite", "gemini-2.5-flash")
    last_err = None
    last_model = None
    for model_name in models:
        last_model = model_name
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
                last_err = f"bad shape: {raw[:200]}"
                continue
            print(f"[ai_parser/gemini] success with {model_name}")
            return data
        except Exception as e:
            last_err = f"{type(e).__name__}: {str(e)[:150]}"
            print(f"[ai_parser/gemini] {model_name} failed: {last_err}")
            continue
    return {"intent": "unknown", "reply": f"AI ขัดข้อง (gemini/{last_model}): {last_err[:200] if last_err else ''}"}


def parse(text: str) -> Dict[str, Any]:
    """Return parsed intent dict. Tries Groq first, then Gemini."""
    if GROQ_API_KEY:
        result = _try_groq(text)
        if result.get("intent") != "unknown" or not GEMINI_API_KEY:
            return result
        # else fall through to Gemini

    if GEMINI_API_KEY:
        return _try_gemini(text)

    return {"intent": "unknown", "reply": "AI parser ยังไม่ได้ตั้งค่า GROQ_API_KEY หรือ GEMINI_API_KEY"}

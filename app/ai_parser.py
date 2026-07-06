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

SYSTEM_PROMPT = """คุณคือผู้ช่วยแปลงข้อความภาษาไทย/อังกฤษ ให้เป็น JSON สำหรับจัดการ to-do list และกิจวัตรประจำวัน
ตอบเป็น JSON อย่างเดียว ห้ามมี markdown หรือ code fence

Schema:
{
  "intent": "add"|"clarify"|"list_today"|"list_tomorrow"|"list_week"|"list_overdue"|"list_urgent"|"list_date"|"list_all"|"search"|"done"|"delete"|"delete_all"|"done_all"|"snooze"|"cancel_recurring"|"add_note"|"set_priority"|"add_routine"|"list_routines"|"delete_routine"|"delete_all_routines"|"update_routine"|"help"|"unknown",
  "tasks": [{"title": "string", "deadline": "YYYY-MM-DD HH:MM" or null, "recurring": "daily"|"weekly:N"|"monthly:D"|null, "priority": "urgent"|"high"|"normal"|"low"|null, "note": "string"|null}],
  "task_id": integer or null,
  "priority": "urgent"|"high"|"normal"|"low"|null,
  "note": "string"|null,
  "keyword": "string"|null,
  "routine": {"title": "string", "time": "HH:MM", "days": "daily|0|0,1,2,3,4", "advance_minutes": 30},
  "routine_id": integer or null,
  "date": "YYYY-MM-DD" or null,
  "reply": "ข้อความตอบกลับสั้นๆ (optional)"
}

กฎทั่วไป:
- ถ้าผู้ใช้สั่งเพิ่มงานหลายอย่าง ให้ list หลายตัวใน tasks
- ถ้าไม่ระบุเวลา ให้ deadline = null  |  ถ้าระบุแค่วัน ใช้ 23:59
- ถ้าจับใจความไม่ได้ → intent="unknown"

⚠️ กฎ clarify (ถามกลับเมื่อข้อมูลไม่ครบ) — สำคัญ:
- intent="clarify" ใช้เมื่อผู้ใช้ต้องการให้ "เตือน" หรือตั้งงานที่ควรมีกำหนดส่ง แต่ "ไม่ได้บอกวันหรือเวลาเลย"
  → คืน {"intent":"clarify","tasks":[{"title":"<ชื่องาน>"}],"reply":"📅 อยากให้เตือนวันไหน เวลาไหนดีครับ?"}
- ⚠️ ห้ามใช้ clarify ถ้าผู้ใช้แค่ "จดไว้"/"โน้ต"/"ไม่รีบ"/"ทำทีหลัง" — พวกนี้ deadline=null ได้ ใช้ intent="add" ตามปกติ
- ⚠️ ถ้ามีวันหรือเวลาอยู่แล้ว (แม้บอกแค่วัน) → intent="add" ไม่ต้อง clarify
ตัวอย่าง clarify:
"เตือนส่งเอกสาร" → {"intent":"clarify","tasks":[{"title":"ส่งเอกสาร"}],"reply":"📅 อยากให้เตือน 'ส่งเอกสาร' วันไหน เวลาไหนดีครับ?"}
"อย่าลืมจ่ายบิล" → {"intent":"clarify","tasks":[{"title":"จ่ายบิล"}],"reply":"📅 อยากให้เตือน 'จ่ายบิล' วันไหน เวลาไหนดีครับ?"}
"จดไว้ ซื้อยา ไม่รีบ" → {"intent":"add","tasks":[{"title":"ซื้อยา","deadline":null,"priority":"low"}]}
- intent="done"/"delete"/"cancel_recurring" ต้องมี task_id
- intent="delete_routine" ต้องมี routine_id
- priority default = "normal" ถ้าไม่ระบุ

กฎ priority:
- "ด่วน"/"urgent"/"สำคัญมาก"/"ทำก่อน"/"urgent" → "urgent"
- "สำคัญ"/"high"/"รีบ" → "high"
- "ไม่รีบ"/"low"/"ทำทีหลัง" → "low"
- ไม่ระบุ → "normal"

⚠️ กฎแยก "งานซ้ำ" vs "กิจวัตร" — สำคัญมาก:
งานซ้ำ (add + recurring) = งาน/ภาระที่ต้อง mark done มี deadline จริง
  ✅ ส่งรายงาน, ประชุม, ส่งการบ้าน, จ่ายบิล, นัดหมาย
กิจวัตร (add_routine) = นิสัย/ไลฟ์สไตล์ที่แค่ต้องการ reminder ไม่ต้อง mark done
  ✅ ออกกำลังกาย, กินยา, นอนหลับ, อ่านหนังสือ, วิ่ง, โยคะ, ทำสมาธิ
ถ้าสงสัย: ถ้ามีคำว่า "ส่ง" / "ประชุม" / "นัด" → งานซ้ำ; ถ้ามีคำว่า "ออกกำลัง" / "กิน" / "นอน" / "อ่าน" / "วิ่ง" → กิจวัตร

กฎงานซ้ำ:
- recurring="daily" | "weekly:N" (0=จันทร์…6=อาทิตย์) | "monthly:D"
- deadline = วันถัดไปที่ตรง + เวลา  ⚠️ ห้าม null ถ้ามีเวลา
- "ยกเลิกซ้ำ 3" → intent="cancel_recurring", task_id=3

⚠️ การแปลงเวลาภาษาไทย:
- "ตี 1-5" = 01:00-05:00  |  "X โมงเช้า" = 06:00-11:00
- "เช้า"=09:00  "สาย"=10:00  "เที่ยง"=12:00
- "บ่าย 1-4" = 13:00-16:00  |  "5-6 โมงเย็น" = 17:00-18:00  |  "เย็น"=18:00
- "1-5 ทุ่ม" = 19:00-23:00  ⚠️ ทุ่ม ≠ โมงเย็น
- "ค่ำ"=20:00  "ดึก"=23:00  "เที่ยงคืน"=00:00

กิจวัตร days: "daily"|"0"(จันทร์)|"1"|"2"|"3"|"4"|"5"(เสาร์)|"6"(อาทิตย์)|"0,1,2,3,4"|"5,6"
advance_minutes default=30 (แจ้งก่อน 30 นาที)

ตัวอย่าง tasks:
"พรุ่งนี้ส่งรายงาน 6 โมงเย็น" → {"intent":"add","tasks":[{"title":"ส่งรายงาน","deadline":"<พรุ่งนี้> 18:00","recurring":null}]}
"ทุกศุกร์ส่งรายงาน 5 โมงเย็น" → {"intent":"add","tasks":[{"title":"ส่งรายงาน","deadline":"<ศุกร์หน้า> 17:00","recurring":"weekly:4"}]}
"ทุกจันทร์ประชุมทีม 9 โมง" → {"intent":"add","tasks":[{"title":"ประชุมทีม","deadline":"<จันทร์หน้า> 09:00","recurring":"weekly:0"}]}
"วันนี้มีอะไรบ้าง"/"งานวันนี้" → {"intent":"list_today"}
"งานพรุ่งนี้"/"พรุ่งนี้มีอะไร" → {"intent":"list_tomorrow"}
"งานอาทิตย์นี้"/"สัปดาห์นี้" → {"intent":"list_week"}
"งานที่ค้าง"/"เลยกำหนดมีอะไร" → {"intent":"list_overdue"}
"งานด่วนมีอะไร"/"งาน priority สูง" → {"intent":"list_urgent"}
"งานวันที่ 20"/"วัน 25 พ.ค. มีงานอะไร" → {"intent":"list_date","date":"YYYY-MM-20"}
"งานทั้งหมด"/"มีงานอะไรบ้าง" → {"intent":"list_all"}
"หางาน KBank"/"ค้นหางาน invoice" → {"intent":"search","keyword":"KBank"}
"งาน 3 เสร็จแล้ว" → {"intent":"done","task_id":3}
"ลบงานที่ 2" → {"intent":"delete","task_id":2}
"ลบทั้งหมด"/"เคลียร์งานหมด" → {"intent":"delete_all"}
"ปิดงานทั้งหมด"/"เสร็จหมดแล้ว" → {"intent":"done_all"}
"เลื่อนงาน 3 เป็นพรุ่งนี้ 20:00" → {"intent":"snooze","task_id":3,"deadline":"<พรุ่งนี้> 20:00"}
"ยกเลิกซ้ำงาน 3" → {"intent":"cancel_recurring","task_id":3}
"เพิ่มโน้ต งาน 3 ว่า ติดต่อต้น" → {"intent":"add_note","task_id":3,"note":"ติดต่อต้น"}
"ตั้งงาน 5 เป็น urgent"/"งาน 2 ด่วนมาก" → {"intent":"set_priority","task_id":5,"priority":"urgent"}
"งานด่วน ส่งสัญญาก่อนเที่ยง" → {"intent":"add","tasks":[{"title":"ส่งสัญญา","deadline":"<วันนี้> 12:00","priority":"urgent"}]}
"จดไว้ ซื้อยา ไม่รีบ" → {"intent":"add","tasks":[{"title":"ซื้อยา","deadline":null,"priority":"low"}]}

ตัวอย่าง routines:
"ออกกำลังกายทุกวัน 18:00" → {"intent":"add_routine","routine":{"title":"ออกกำลังกาย","time":"18:00","days":"daily","advance_minutes":30}}
"วิ่งทุกเช้า 6 โมง" → {"intent":"add_routine","routine":{"title":"วิ่ง","time":"06:00","days":"daily","advance_minutes":30}}
"กินยาทุกวัน ตี 1 แจ้งก่อน 15 นาที" → {"intent":"add_routine","routine":{"title":"กินยา","time":"01:00","days":"daily","advance_minutes":15}}
"โยคะทุกเสาร์-อาทิตย์ 7 โมงเช้า" → {"intent":"add_routine","routine":{"title":"โยคะ","time":"07:00","days":"5,6","advance_minutes":30}}
"กิจวัตรของฉัน"/"กิจวัตรมีอะไร" → {"intent":"list_routines"}
"ลบกิจวัตรที่ 2" → {"intent":"delete_routine","routine_id":2}
"ลบกิจวัตรทั้งหมด" → {"intent":"delete_all_routines"}
"แก้กิจวัตร 1 เป็น 19:00" → {"intent":"update_routine","routine_id":1,"routine":{"time":"19:00"}}
"เปลี่ยนกิจวัตร 2 แจ้งก่อน 1 ชั่วโมง" → {"intent":"update_routine","routine_id":2,"routine":{"advance_minutes":60}}
"แก้กิจวัตร 3 เป็นวันจันทร์-ศุกร์" → {"intent":"update_routine","routine_id":3,"routine":{"days":"0,1,2,3,4"}}
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

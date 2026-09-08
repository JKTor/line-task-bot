"""JSON API for writing/reading the plan from outside LINE (e.g. Claude Code).

Every route is gated by a shared secret in the `X-API-Key` header. The secret is
`API_SECRET` if set, otherwise it falls back to `CRON_SECRET` so this works on an
existing deploy without adding a new env var.

Tasks written here land in the same `tasks` table the LINE bot reads, so
"วันนี้" / "พรุ่งนี้" / "ทั้งหมด" in LINE pick them up with no extra code.
The free-plan task cap is deliberately NOT enforced here — this key belongs to
the bot's owner, not to a customer.
"""
import os
from datetime import datetime, timedelta
from typing import List, Optional

import pytz
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Routine, Task, User
from app.parser import TZ, _to_utc_naive, format_deadline, now_local

router = APIRouter(prefix="/api", tags=["api"])

_PRIORITY_VALID = ("urgent", "high", "normal", "low")


def _api_secret() -> str:
    return os.getenv("API_SECRET") or os.getenv("CRON_SECRET") or ""


def require_key(x_api_key: str = Header(default="")):
    secret = _api_secret()
    if not secret:
        raise HTTPException(503, "API_SECRET/CRON_SECRET not configured")
    if x_api_key != secret:
        raise HTTPException(401, "Unauthorized")
    return True


# ── time helpers ──────────────────────────────────────────────────────────────

def parse_deadline(raw: Optional[str]) -> Optional[datetime]:
    """Accept 'YYYY-MM-DD', 'YYYY-MM-DD HH:MM' or ISO. Bangkok time in, UTC-naive out.

    A bare date means end of that day (23:59) — same convention as parser.py.
    """
    if raw is None or str(raw).strip() == "":
        return None
    s = str(raw).strip().replace("T", " ")
    if s.endswith("Z"):
        s = s[:-1]
    for fmt, eod in (("%Y-%m-%d %H:%M:%S", False),
                     ("%Y-%m-%d %H:%M", False),
                     ("%Y-%m-%d", True)):
        try:
            dt = datetime.strptime(s, fmt)
        except ValueError:
            continue
        if eod:
            dt = dt.replace(hour=23, minute=59)
        return _to_utc_naive(dt)
    raise HTTPException(422, f"bad deadline format: {raw!r} (use YYYY-MM-DD or YYYY-MM-DD HH:MM)")


def _local_day_bounds(target_date):
    """UTC-naive [start, end) covering one Bangkok calendar day."""
    start_local = TZ.localize(datetime.combine(target_date, datetime.min.time()))
    end_local = start_local + timedelta(days=1)
    return (start_local.astimezone(pytz.utc).replace(tzinfo=None),
            end_local.astimezone(pytz.utc).replace(tzinfo=None))


def task_dict(t: Task) -> dict:
    local = None
    if t.deadline is not None:
        local = pytz.utc.localize(t.deadline).astimezone(TZ).strftime("%Y-%m-%d %H:%M")
    return {
        "id": t.id,
        "title": t.title,
        "deadline": local,                       # Bangkok time, null = backlog
        "deadline_text": format_deadline(t.deadline),
        "done": t.done,
        "priority": t.priority,
        "note": t.note,
        "recurring": t.recurring,
    }


# ── schemas ───────────────────────────────────────────────────────────────────

class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    deadline: Optional[str] = None               # null = backlog (no date)
    priority: str = "normal"
    note: Optional[str] = Field(default=None, max_length=500)
    recurring: Optional[str] = None


class TasksIn(BaseModel):
    user_id: Optional[str] = None                # defaults to the only user
    items: List[TaskIn]


class TaskPatch(BaseModel):
    user_id: Optional[str] = None
    title: Optional[str] = None
    deadline: Optional[str] = None
    clear_deadline: bool = False                 # explicit: move back to backlog
    done: Optional[bool] = None
    priority: Optional[str] = None
    note: Optional[str] = None


# ── user resolution ───────────────────────────────────────────────────────────

def resolve_user(db: Session, user_id: Optional[str]) -> str:
    """Use the given id, or fall back to the single registered user."""
    if user_id:
        return user_id
    users = db.query(User).order_by(User.id.asc()).all()
    if len(users) == 1:
        return users[0].line_user_id
    if not users:
        raise HTTPException(400, "no users registered — pass user_id explicitly")
    raise HTTPException(400, f"{len(users)} users registered — pass user_id explicitly")


# ── routes ────────────────────────────────────────────────────────────────────

@router.get("/users", dependencies=[Depends(require_key)])
def list_users(db: Session = Depends(get_db)):
    users = db.query(User).order_by(User.id.asc()).all()
    return {"users": [
        {"line_user_id": u.line_user_id, "display_name": u.display_name, "plan": u.plan}
        for u in users
    ]}


@router.get("/tasks", dependencies=[Depends(require_key)])
def list_tasks(scope: str = "all", user_id: Optional[str] = None,
               limit: int = 200, db: Session = Depends(get_db)):
    """scope: today | tomorrow | week | backlog | overdue | dated | done | all"""
    uid = resolve_user(db, user_id)
    q = db.query(Task).filter(Task.user_id == uid)
    now_utc = datetime.utcnow()

    if scope == "done":
        q = q.filter(Task.done == True)  # noqa: E712
    else:
        q = q.filter(Task.done == False)  # noqa: E712

    if scope in ("today", "tomorrow"):
        day = now_local().date() + (timedelta(days=1) if scope == "tomorrow" else timedelta(0))
        start, end = _local_day_bounds(day)
        q = q.filter(Task.deadline.isnot(None), Task.deadline >= start, Task.deadline < end)
    elif scope == "week":
        start, _ = _local_day_bounds(now_local().date())
        _, end = _local_day_bounds(now_local().date() + timedelta(days=6))
        q = q.filter(Task.deadline.isnot(None), Task.deadline >= start, Task.deadline < end)
    elif scope == "backlog":
        q = q.filter(Task.deadline.is_(None))
    elif scope == "overdue":
        q = q.filter(Task.deadline.isnot(None), Task.deadline < now_utc)
    elif scope == "dated":
        q = q.filter(Task.deadline.isnot(None))
    elif scope not in ("all", "done"):
        raise HTTPException(422, f"unknown scope: {scope}")

    tasks = q.order_by(Task.deadline.is_(None), Task.deadline.asc()).limit(limit).all()
    return {"user_id": uid, "scope": scope, "count": len(tasks),
            "tasks": [task_dict(t) for t in tasks]}


@router.post("/tasks", dependencies=[Depends(require_key)])
def create_tasks(payload: TasksIn, db: Session = Depends(get_db)):
    uid = resolve_user(db, payload.user_id)
    if not payload.items:
        raise HTTPException(422, "items is empty")
    if len(payload.items) > 100:
        raise HTTPException(422, "too many items (max 100 per call)")
    created = []
    for item in payload.items:
        title = item.title.strip()
        if not title:
            continue
        task = Task(
            user_id=uid,
            title=title,
            deadline=parse_deadline(item.deadline),
            priority=item.priority if item.priority in _PRIORITY_VALID else "normal",
            note=item.note,
            recurring=item.recurring,
        )
        db.add(task)
        created.append(task)
    db.commit()
    for t in created:
        db.refresh(t)
    return {"ok": True, "created": len(created), "tasks": [task_dict(t) for t in created]}


@router.patch("/tasks/{task_id}", dependencies=[Depends(require_key)])
def update_task(task_id: int, payload: TaskPatch, db: Session = Depends(get_db)):
    uid = resolve_user(db, payload.user_id)
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == uid).first()
    if not task:
        raise HTTPException(404, f"task #{task_id} not found")

    if payload.title is not None:
        task.title = payload.title.strip()
    if payload.clear_deadline:
        task.deadline = None
        task.notified = False
    elif payload.deadline is not None:
        task.deadline = parse_deadline(payload.deadline)
        task.notified = False           # re-arm the reminder for the new time
    if payload.priority is not None:
        if payload.priority not in _PRIORITY_VALID:
            raise HTTPException(422, f"bad priority: {payload.priority}")
        task.priority = payload.priority
    if payload.note is not None:
        task.note = payload.note
    if payload.done is not None:
        task.done = payload.done
        task.completed_at = datetime.utcnow() if payload.done else None

    db.commit()
    db.refresh(task)
    return {"ok": True, "task": task_dict(task)}


@router.delete("/tasks/{task_id}", dependencies=[Depends(require_key)])
def delete_task(task_id: int, user_id: Optional[str] = None, db: Session = Depends(get_db)):
    uid = resolve_user(db, user_id)
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == uid).first()
    if not task:
        raise HTTPException(404, f"task #{task_id} not found")
    title = task.title
    db.delete(task)
    db.commit()
    return {"ok": True, "deleted": task_id, "title": title}


@router.get("/routines", dependencies=[Depends(require_key)])
def list_routines(user_id: Optional[str] = None, db: Session = Depends(get_db)):
    uid = resolve_user(db, user_id)
    rs = (db.query(Routine).filter(Routine.user_id == uid)
          .order_by(Routine.time_hour, Routine.time_minute).all())
    return {"user_id": uid, "count": len(rs), "routines": [
        {"id": r.id, "title": r.title,
         "time": f"{r.time_hour:02d}:{r.time_minute:02d}", "days": r.days}
        for r in rs
    ]}

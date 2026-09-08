"""Subscription plan enforcement."""
import os
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Task, User
from app.auth import is_plan_active

from app.config import APP_BASE_URL

FREE_MAX_TASKS = 30  # active (undone) tasks


def check_can_add_task(db: Session, line_user_id: str) -> dict:
    """
    Return {"ok": True} or {"ok": False, "message": str}
    Called before creating a new task.
    """
    user = db.query(User).filter_by(line_user_id=line_user_id).first()

    # Free plan check
    if not user or user.plan == "free" or not is_plan_active(user):
        active = db.query(Task).filter_by(user_id=line_user_id, done=False).count()
        if active >= FREE_MAX_TASKS:
            return {
                "ok": False,
                "message": (
                    f"⚠️ ครบ {FREE_MAX_TASKS} task แล้ว (Free plan)\n"
                    f"อัพเกรดเป็น Pro ได้ที่:\n{APP_BASE_URL}/dashboard"
                ),
            }

    return {"ok": True}


def get_user_plan(db: Session, line_user_id: str) -> str:
    user = db.query(User).filter_by(line_user_id=line_user_id).first()
    if not user:
        return "free"
    if not is_plan_active(user):
        return "expired"
    return user.plan

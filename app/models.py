from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String

from app.database import Base


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(64), index=True, nullable=False)
    title = Column(String(500), nullable=False)
    deadline = Column(DateTime, nullable=True)
    done = Column(Boolean, default=False, nullable=False)
    notified = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    recurring = Column(String(30), nullable=True)
    completed_at = Column(DateTime, nullable=True)
    priority = Column(String(10), default="normal", nullable=False, server_default="normal")
    note = Column(String(500), nullable=True)
    overdue_notified_date = Column(String(10), nullable=True)


class Routine(Base):
    __tablename__ = "routines"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), index=True, nullable=False)
    title = Column(String(500), nullable=False)
    time_hour = Column(Integer, nullable=False)
    time_minute = Column(Integer, nullable=False)
    days = Column(String(20), default="daily", nullable=False)
    advance_minutes = Column(Integer, default=30, nullable=False)
    last_notified_date = Column(String(10), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    line_user_id = Column(String(64), unique=True, index=True, nullable=False)
    display_name = Column(String(100), nullable=True)
    picture_url = Column(String(300), nullable=True)
    plan = Column(String(20), default="free", nullable=False)      # free | pro | team
    plan_expires_at = Column(DateTime, nullable=True)              # null = forever
    notion_token = Column(String(300), nullable=True)
    notion_db_id = Column(String(100), nullable=True)
    quiet_start = Column(Integer, nullable=True)                   # 0-23
    quiet_end = Column(Integer, nullable=True)                     # 0-23
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class PendingClarify(Base):
    """A task the bot is waiting for the user to finish (e.g. supply a date).

    One row per user (line_user_id). Created when the AI returns intent="clarify";
    consumed (deleted) when the user's next message answers the question, or when
    it expires. New table → created automatically by Base.metadata.create_all().
    """
    __tablename__ = "pending_clarify"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), unique=True, index=True, nullable=False)
    title = Column(String(500), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class AppState(Base):
    """Tiny key/value store for system-wide flags (not per-user).

    Used to dedupe the weekly summary: we piggyback it on the reliable 5-min
    /cron/check instead of a fragile weekly cron, and record which ISO week was
    already sent here. New table → created automatically by create_all().
    """
    __tablename__ = "app_state"

    key = Column(String(50), primary_key=True)
    value = Column(String(100), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class UnknownMessage(Base):
    __tablename__ = "unknown_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), index=True, nullable=False)
    text = Column(String(1000), nullable=False)    # สิ่งที่ user พิม
    ai_intent = Column(String(50), nullable=True)  # intent ที่ AI คืนมา
    resolved = Column(Boolean, default=False)      # admin mark ว่าจัดการแล้ว
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

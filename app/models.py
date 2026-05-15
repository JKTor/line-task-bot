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


class UnknownMessage(Base):
    __tablename__ = "unknown_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), index=True, nullable=False)
    text = Column(String(1000), nullable=False)    # สิ่งที่ user พิม
    ai_intent = Column(String(50), nullable=True)  # intent ที่ AI คืนมา
    resolved = Column(Boolean, default=False)      # admin mark ว่าจัดการแล้ว
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

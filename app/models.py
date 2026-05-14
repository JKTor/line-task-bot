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
    recurring = Column(String(30), nullable=True)     # "daily"|"weekly:N"|"monthly:D"
    completed_at = Column(DateTime, nullable=True)    # set when done=True


class Routine(Base):
    __tablename__ = "routines"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), index=True, nullable=False)
    title = Column(String(500), nullable=False)
    time_hour = Column(Integer, nullable=False)    # 0–23
    time_minute = Column(Integer, nullable=False)  # 0–59
    days = Column(String(20), default="daily", nullable=False)  # "daily" or "0,1,4" (weekday 0=Mon)
    advance_minutes = Column(Integer, default=30, nullable=False)
    last_notified_date = Column(String(10), nullable=True)  # "YYYY-MM-DD" prevents duplicates
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

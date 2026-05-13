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

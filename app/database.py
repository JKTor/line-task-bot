import os
import time

from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./tasks.db")

# Render's Postgres URL starts with postgres:// but SQLAlchemy 2.x needs postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

_is_pg = DATABASE_URL.startswith("postgresql")

if _is_pg:
    # Neon serverless drops idle connections; NullPool creates a fresh connection
    # per request to avoid stale-connection SSL errors (recommended by Neon docs).
    from sqlalchemy.pool import NullPool
    engine = create_engine(DATABASE_URL, poolclass=NullPool)
else:
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
    )

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def migrate_db() -> None:
    """Add new columns to existing tables without Alembic."""
    ts_type = "TIMESTAMP" if _is_pg else "DATETIME"
    migrations = [
        "ALTER TABLE tasks ADD COLUMN recurring VARCHAR(30)",
        f"ALTER TABLE tasks ADD COLUMN completed_at {ts_type}",
    ]
    with engine.connect() as conn:
        for stmt in migrations:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception:
                conn.rollback()  # clear aborted transaction before next statement


def init_db(retries: int = 10, delay: float = 3.0) -> None:
    from app import models  # noqa: F401
    for attempt in range(1, retries + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            Base.metadata.create_all(bind=engine)
            migrate_db()
            print(f"[init_db] connected on attempt {attempt}")
            return
        except Exception as e:
            print(f"[init_db] attempt {attempt}/{retries} failed: {e}")
            if attempt < retries:
                time.sleep(delay)
    print("[init_db] WARNING: could not connect to DB, continuing anyway")

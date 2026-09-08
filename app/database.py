import os
import time
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./tasks.db")

# Render's Postgres URL starts with postgres:// but SQLAlchemy 2.x needs postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

_is_pg = DATABASE_URL.startswith("postgresql")

if _is_pg:
    # Fix potential truncated sslmode (e.g. "requ" instead of "require")
    # then pass it explicitly via connect_args to avoid psycopg2 URL parsing bugs.
    _VALID_SSL = {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}
    _p = urlparse(DATABASE_URL)
    _q = {k: v for k, v in parse_qs(_p.query, keep_blank_values=True).items()
          if k != "sslmode"}
    _ssl_raw = parse_qs(_p.query, keep_blank_values=True).get("sslmode", ["require"])[0]
    _ssl = _ssl_raw if _ssl_raw in _VALID_SSL else "require"
    _clean_url = urlunparse(_p._replace(query=urlencode(_q, doseq=True)))
    engine = create_engine(
        _clean_url,
        connect_args={"sslmode": _ssl},
        pool_pre_ping=True,
    )
    print(f"[db] using sslmode={_ssl} (raw was: {_ssl_raw!r})")
else:
    # SQLite is fine for local dev, but on a hosted (non-localhost) deploy it means
    # the DB lives on ephemeral disk → data is wiped on every redeploy/restart.
    from app.config import APP_BASE_URL as _base_url
    if "localhost" not in _base_url and "127.0.0.1" not in _base_url:
        print(
            "[db] WARNING: running on SQLite in what looks like a production deploy "
            f"(APP_BASE_URL={_base_url!r}). Data will be LOST on redeploy — "
            "set DATABASE_URL to a Postgres connection string."
        )
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
        "ALTER TABLE tasks ADD COLUMN priority VARCHAR(10) DEFAULT 'normal'",
        "ALTER TABLE tasks ADD COLUMN note VARCHAR(500)",
        "ALTER TABLE tasks ADD COLUMN overdue_notified_date VARCHAR(10)",
    ]
    with engine.connect() as conn:
        for stmt in migrations:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass


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

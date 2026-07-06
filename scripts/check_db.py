"""Quick sanity check for a DATABASE_URL before wiring it into Render.

Usage:
    # PowerShell
    $env:DATABASE_URL="postgresql://user:pass@host/db?sslmode=require"; python scripts/check_db.py

    # bash
    DATABASE_URL="postgresql://user:pass@host/db?sslmode=require" python scripts/check_db.py

It reuses the app's own engine/init logic, so if this passes, the real deploy
will connect the same way. It creates the tables (safe/idempotent) and lists them.
"""
import os
import sys

# make `app` importable when run from the repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect, text

from app.database import engine, init_db, _is_pg, DATABASE_URL


def main() -> int:
    kind = "Postgres" if _is_pg else "SQLite"
    # never print credentials
    safe = DATABASE_URL.split("@")[-1] if "@" in DATABASE_URL else DATABASE_URL
    print(f"[check_db] target: {kind} ({safe})")

    if not _is_pg:
        print("[check_db] NOTE: this is not a Postgres URL. Set DATABASE_URL to your "
              "Neon connection string to test the real target.")

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("[check_db] connection: OK")
    except Exception as e:
        print(f"[check_db] connection FAILED: {e}")
        return 1

    try:
        init_db(retries=1)
        tables = inspect(engine).get_table_names()
        print(f"[check_db] tables ({len(tables)}): {', '.join(sorted(tables)) or '(none)'}")
    except Exception as e:
        print(f"[check_db] table setup FAILED: {e}")
        return 1

    print("[check_db] all good — safe to set this DATABASE_URL in Render.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

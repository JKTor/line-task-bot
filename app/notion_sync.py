"""Notion sync — push new tasks to user's Notion database."""
from datetime import datetime
from typing import Optional

try:
    from notion_client import Client
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False


def sync_task(notion_token: str, notion_db_id: str, title: str,
              deadline: Optional[datetime] = None) -> bool:
    if not _AVAILABLE or not notion_token or not notion_db_id:
        return False
    try:
        client = Client(auth=notion_token)
        props: dict = {"Name": {"title": [{"text": {"content": title}}]}}
        if deadline:
            import pytz
            from app.parser import TZ
            local_dt = pytz.utc.localize(deadline).astimezone(TZ)
            props["Due Date"] = {"date": {"start": local_dt.strftime("%Y-%m-%dT%H:%M:%S+07:00")}}
        client.pages.create(parent={"database_id": notion_db_id}, properties=props)
        return True
    except Exception as e:
        print(f"[notion_sync] failed: {e}")
        return False

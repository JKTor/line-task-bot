"""LINE Login OAuth2 + JWT session management."""
import os
import secrets
from datetime import datetime, timedelta
from typing import Optional

import httpx
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.models import User

LINE_LOGIN_CLIENT_ID = os.getenv("LINE_LOGIN_CLIENT_ID", "")
LINE_LOGIN_SECRET = os.getenv("LINE_LOGIN_SECRET", "")
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:8000")
JWT_SECRET = os.getenv("JWT_SECRET", "change-me-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_DAYS = 30

CALLBACK_URL = f"{APP_BASE_URL}/auth/callback"
LINE_AUTHORIZE_URL = "https://access.line.me/oauth2/v2.1/authorize"
LINE_TOKEN_URL = "https://api.line.me/oauth2/v2.1/token"
LINE_PROFILE_URL = "https://api.line.me/v2/profile"


def get_line_login_url() -> str:
    state = secrets.token_urlsafe(16)
    params = (
        f"response_type=code"
        f"&client_id={LINE_LOGIN_CLIENT_ID}"
        f"&redirect_uri={CALLBACK_URL}"
        f"&state={state}"
        f"&scope=profile%20openid"
    )
    return f"{LINE_AUTHORIZE_URL}?{params}"


async def exchange_code_for_profile(code: str) -> Optional[dict]:
    """Exchange auth code for LINE profile. Returns profile dict or None."""
    async with httpx.AsyncClient() as client:
        try:
            token_resp = await client.post(LINE_TOKEN_URL, data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": CALLBACK_URL,
                "client_id": LINE_LOGIN_CLIENT_ID,
                "client_secret": LINE_LOGIN_SECRET,
            })
            if token_resp.status_code != 200:
                print(f"[auth] token exchange failed: {token_resp.text}")
                return None
            access_token = token_resp.json().get("access_token")

            profile_resp = await client.get(
                LINE_PROFILE_URL,
                headers={"Authorization": f"Bearer {access_token}"}
            )
            if profile_resp.status_code != 200:
                return None
            return profile_resp.json()
        except Exception as e:
            print(f"[auth] error: {e}")
            return None


def get_or_create_user(db: Session, line_user_id: str,
                        display_name: str = "", picture_url: str = "") -> tuple:
    """Return (user, is_new). Creates user record if first time."""
    user = db.query(User).filter_by(line_user_id=line_user_id).first()
    is_new = False
    if not user:
        user = User(
            line_user_id=line_user_id,
            display_name=display_name,
            picture_url=picture_url,
            plan="free",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        is_new = True
    elif display_name and user.display_name != display_name:
        user.display_name = display_name
        user.picture_url = picture_url
        db.commit()
    return user, is_new


def create_session_token(line_user_id: str) -> str:
    expire = datetime.utcnow() + timedelta(days=JWT_EXPIRE_DAYS)
    return jwt.encode(
        {"sub": line_user_id, "exp": expire},
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )


def decode_session_token(token: str) -> Optional[str]:
    """Return line_user_id or None if invalid/expired."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None


def get_user_from_db(db: Session, line_user_id: str) -> Optional[User]:
    return db.query(User).filter_by(line_user_id=line_user_id).first()


def is_plan_active(user: User) -> bool:
    if user.plan == "free":
        return True
    if user.plan_expires_at is None:
        return True
    return user.plan_expires_at > datetime.utcnow()

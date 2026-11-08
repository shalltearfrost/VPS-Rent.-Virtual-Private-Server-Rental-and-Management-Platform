import hashlib
import secrets
from datetime import UTC, datetime
from typing import Annotated

from cryptography.fernet import Fernet
from fastapi import Depends, HTTPException, Request
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import LoginSession, User

Db = Annotated[Session, Depends(get_db)]
password_hasher = PasswordHash.recommended()
dummy_hash = password_hasher.hash(secrets.token_urlsafe(32))


def now() -> datetime:
    return datetime.now(UTC)


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def encrypt_password(value: str) -> str:
    key = get_settings().credential_key.get_secret_value().encode()
    return Fernet(key).encrypt(value.encode()).decode()


def decrypt_password(value: str) -> str:
    key = get_settings().credential_key.get_secret_value().encode()
    return Fernet(key).decrypt(value.encode()).decode()


def current_user(request: Request, db: Db) -> User:
    token = request.cookies.get("vps_session", "")
    session = db.scalar(
        select(LoginSession).where(
            LoginSession.token_hash == token_hash(token),
            LoginSession.expires_at > now(),
        )
    )
    if not session:
        raise HTTPException(401, "Sign in to continue")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        csrf = request.headers.get("x-csrf-token", "")
        if not secrets.compare_digest(csrf, session.csrf_token):
            raise HTTPException(403, "Invalid CSRF token")
    request.state.login_session = session
    return db.get(User, session.user_id)


CurrentUser = Annotated[User, Depends(current_user)]


def require_role(*roles: str):
    def check(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(403, "This action requires another role")
        return user

    return check


Customer = Annotated[User, Depends(require_role("customer"))]
Operator = Annotated[User, Depends(require_role("operator"))]
Manager = Annotated[User, Depends(require_role("manager"))]
Support = Annotated[User, Depends(require_role("support"))]

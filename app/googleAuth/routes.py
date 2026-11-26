"""Google sign-in endpoints (OAuth 2.0 authorization code flow + PKCE)."""

import base64
import hashlib
import secrets
from datetime import timedelta

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.api import begin_session
from app.config import get_settings

# Call through the module (googleAuth.exchange_code_for_tokens) so tests
# can replace the Google HTTP call with monkeypatch.
from app.googleAuth import auth as googleAuth
from app.models import User
from app.security import Db, current_user, now

router = APIRouter(prefix="/api", tags=["auth"])

GOOGLE_COOKIE = "g_oauth"
GOOGLE_COOKIE_PATH = "/api/auth/google"


@router.get("/auth/google/config")
def google_config():
    settings = get_settings()
    return {
        "enabled": bool(
            settings.google_client_id
            and settings.google_client_secret.get_secret_value()
        )
    }


def recent_login(request, db):
    try:
        user = current_user(request, db)
    except HTTPException:
        return None
    at = request.state.login_session.authenticated_at
    if at is None or at < now() - timedelta(minutes=10):
        return None
    return user


@router.get("/auth/google/start")
def google_start(request: Request, db: Db, link: bool = False):
    settings = get_settings()
    if link:
        owner = recent_login(request, db)
        if owner is None:
            return RedirectResponse("/#login/google-relogin", status_code=303)
    verifier = secrets.token_urlsafe(64)
    state = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    try:
        url = googleAuth.authorization_url(state, challenge)
    except googleAuth.GoogleAuthError as error:
        raise HTTPException(404, "Google sign-in is not configured") from error

    response = RedirectResponse(url, status_code=302)
    response.set_cookie(
        GOOGLE_COOKIE,
        f"{state}.{verifier}" + (f".{owner.id}" if link else ""),
        httponly=True,
        samesite="lax",
        max_age=600,
        path=GOOGLE_COOKIE_PATH,
        secure=settings.cookie_secure,
    )
    return response


def google_user(
    db: Db, sub: str, email: str, owner: User | None
) -> User | None:
    if owner is not None:
        account = db.scalar(
            select(User)
            .where(User.id == owner.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if account.email != email or account.google_sub not in (None, sub):
            return None
        linked = db.scalar(select(User.id).where(User.google_sub == sub))
        if linked is not None and linked != account.id:
            return None
        account.google_sub = sub
        return account
    user = db.scalar(select(User).where(User.google_sub == sub))
    if user is None:
        db.execute(
            insert(User)
            .values(email=email, google_sub=sub, role="customer")
            .on_conflict_do_nothing()
        )
        user = db.scalar(select(User).where(User.google_sub == sub))
    return user


@router.get("/auth/google/callback")
def google_callback(
    request: Request,
    db: Db,
    code: str = "",
    state: str = "",
    error: str = "",
):
    # Browser navigation, not fetch: answer with redirects, never JSON.
    failed = RedirectResponse("/#login/google-failed", status_code=303)
    failed.delete_cookie(GOOGLE_COOKIE, path=GOOGLE_COOKIE_PATH)
    saved_state, _, verifier = request.cookies.get(
        GOOGLE_COOKIE, ""
    ).partition(".")
    verifier, _, owner_id = verifier.partition(".")
    if (
        error
        or not code
        or not saved_state
        or not verifier
        or not secrets.compare_digest(saved_state.encode(), state.encode())
    ):
        return failed
    try:
        tokens = googleAuth.exchange_code_for_tokens(code, verifier)
        sub, email = googleAuth.read_id_token(tokens.get("id_token"))
    except (googleAuth.GoogleAuthError, AttributeError):
        return failed
    owner = recent_login(request, db) if owner_id else None
    if owner_id and (owner is None or str(owner.id) != owner_id):
        return failed
    user = google_user(db, sub, email, owner)
    if user is None:
        return failed

    response = RedirectResponse("/#home", status_code=303)
    begin_session(db, user, response, request)
    response.delete_cookie(GOOGLE_COOKIE, path=GOOGLE_COOKIE_PATH)
    return response

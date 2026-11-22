"""Google sign-in endpoints (OAuth 2.0 authorization code flow + PKCE)."""

import base64
import hashlib
import secrets

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.api import begin_session
from app.config import get_settings

# Call through the module (googleAuth.exchange_code_for_tokens) so tests
# can replace the Google HTTP call with monkeypatch.
from app.googleAuth import auth as googleAuth
from app.models import User
from app.security import Db

router = APIRouter(prefix="/api", tags=["auth"])

GOOGLE_COOKIE = "g_oauth"
GOOGLE_COOKIE_PATH = "/api/auth/google"


@router.get("/auth/google/start")
def google_start():
    settings = get_settings()
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
        f"{state}.{verifier}",
        httponly=True,
        samesite="lax",
        max_age=600,
        path=GOOGLE_COOKIE_PATH,
        secure=settings.cookie_secure,
    )
    return response


def google_user(db: Db, sub: str, email: str) -> User | None:
    """Find, link or create the account for a Google identity.
    None means the email belongs to an account that is already linked to
    a different Google identity.
    """
    user = db.scalar(select(User).where(User.google_sub == sub))
    if user:
        return user
    user = db.scalar(select(User).where(User.email == email).with_for_update())
    if user:
        if user.google_sub is not None:
            return None
        user.google_sub = sub
        return user
    user = User(email=email, google_sub=sub, role="customer")
    db.add(user)
    db.flush()
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
    user = google_user(db, sub, email)
    if user is None:
        return failed

    response = RedirectResponse("/#home", status_code=303)
    begin_session(db, user, response, request)
    response.delete_cookie(GOOGLE_COOKIE, path=GOOGLE_COOKIE_PATH)
    return response

import base64
import binascii
import json
import time
from urllib.parse import urlencode

import httpx

from app.config import get_settings

AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
ISSUERS = {"https://accounts.google.com", "accounts.google.com"}


class GoogleAuthError(Exception):
    """Google sign-in could not be completed."""


def authorization_url(state: str, code_challenge: str) -> str:
    """URL of Google's consent page the browser is redirected to."""
    settings = get_settings()
    if (
        not settings.google_client_id
        or not settings.google_client_secret.get_secret_value()
    ):
        raise GoogleAuthError("Google sign-in is not configured")
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": "openid email",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{AUTHORIZATION_URL}?{urlencode(params)}"


def exchange_code_for_tokens(code: str, code_verifier: str) -> dict:
    """Exchange the authorization code for Google's tokens."""
    settings = get_settings()
    secret = settings.google_client_secret.get_secret_value()
    if not settings.google_client_id or not secret:
        raise GoogleAuthError("Google sign-in is not configured")
    data = {
        "code": code,
        "code_verifier": code_verifier,
        "client_id": settings.google_client_id,
        "client_secret": secret,
        "redirect_uri": settings.google_redirect_uri,
        "grant_type": "authorization_code",
    }
    try:
        response = httpx.post(TOKEN_URL, data=data, timeout=10)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as error:
        # Expired or reused codes come back as 400 invalid_grant.
        raise GoogleAuthError("Google token exchange failed") from error


def read_id_token(id_token: str) -> tuple[str, str]:
    """Return (sub, email) from an ID token received from TOKEN_URL.

    The token came straight from Google over TLS in exchange for our
    client secret, so OpenID Connect Core 3.1.3.7 lets us skip the
    signature check. The claims are still checked.
    """
    if not isinstance(id_token, str):
        raise GoogleAuthError("Google returned no ID token")
    try:
        payload = id_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
    except (IndexError, ValueError, binascii.Error) as error:
        raise GoogleAuthError("Malformed Google ID token") from error
    if not isinstance(claims, dict):
        raise GoogleAuthError("Malformed Google ID token")
    if claims.get("iss") not in ISSUERS:
        raise GoogleAuthError("ID token was not issued by Google")
    if claims.get("aud") != get_settings().google_client_id:
        raise GoogleAuthError("ID token was issued to another client")
    exp = claims.get("exp")
    if not isinstance(exp, int | float) or exp < time.time():
        raise GoogleAuthError("ID token has expired")
    if claims.get("email_verified") is not True:
        raise GoogleAuthError("Google email address is not verified")
    sub, email = claims.get("sub"), claims.get("email")
    if (
        not isinstance(sub, str)
        or not 1 <= len(sub) <= 255
        or not isinstance(email, str)
        or not 1 <= len(email) <= 254
    ):
        raise GoogleAuthError("ID token lacks sub or email")
    return sub, email.lower()

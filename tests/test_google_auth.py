import base64
import hashlib
import json
import time
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.googleAuth import auth as google_auth
from app.main import app
from app.models import User
from tests.conftest import PASSWORD

CLIENT_ID = "test-client.apps.googleusercontent.com"
FAILED = "/#login/google-failed"


def id_token(**overrides) -> str:
    claims = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": "google-123",
        "email": "Person@Example.com",
        "email_verified": True,
        "exp": int(time.time()) + 3600,
        **overrides,
    }
    part = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode()
    return f"header.{part.rstrip('=')}.signature"


@pytest.fixture
def google(monkeypatch):
    """Configure Google sign-in and stand in for its token endpoint."""
    monkeypatch.setenv("GOOGLE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-secret")
    get_settings.cache_clear()
    fake = {"token": id_token(), "calls": []}

    def exchange(code, verifier):
        fake["calls"].append((code, verifier))
        if code == "bad":
            raise google_auth.GoogleAuthError("invalid_grant")
        return {"access_token": "unused", "id_token": fake["token"]}

    monkeypatch.setattr(google_auth, "exchange_code_for_tokens", exchange)
    yield fake
    get_settings.cache_clear()


def sign_in(client, code="good", state=None, link=False):
    started = client.get(
        "/api/auth/google/start", params={"link": link}, follow_redirects=False
    )
    assert started.status_code == 302
    query = parse_qs(urlsplit(started.headers["location"]).query)
    return (
        started,
        query,
        client.get(
            "/api/auth/google/callback",
            params={"code": code, "state": state or query["state"][0]},
            follow_redirects=False,
        ),
    )


def test_start_sends_state_and_pkce_challenge(google):
    with TestClient(app) as client:
        started, query, _ = sign_in(client)
    assert started.headers["location"].startswith(
        google_auth.AUTHORIZATION_URL
    )
    assert query["client_id"] == [CLIENT_ID]
    assert query["code_challenge_method"] == ["S256"]
    state, verifier = started.cookies["g_oauth"].split(".")
    assert query["state"] == [state]
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    assert query["code_challenge"] == [challenge]
    assert google["calls"] == [("good", verifier)]


def test_new_google_user_becomes_signed_in_customer(google, db):
    with TestClient(app) as client:
        *_, finished = sign_in(client)
        assert finished.status_code == 303
        assert finished.headers["location"] == "/#home"
        me = client.get("/api/auth/me").json()["user"]
    assert me["email"] == "person@example.com"
    assert me["role"] == "customer"
    user = db.scalar(select(User).where(User.google_sub == "google-123"))
    assert user.password_hash is None


def test_existing_email_is_linked_and_found_by_sub_later(google, accounts, db):
    google["token"] = id_token(email="customer@example.com")
    with TestClient(app) as client:
        assert sign_in(client)[2].headers["location"] == FAILED
        assert (
            client.post(
                "/api/auth/login",
                json={"email": "customer@example.com", "password": PASSWORD},
            ).status_code
            == 200
        )
        assert sign_in(client, link=True)[2].headers["location"] == "/#home"
    user = db.get(User, accounts["customer"].id)
    db.refresh(user)
    assert user.google_sub == "google-123"

    # Google email changed; the stable sub still finds the same account.
    google["token"] = id_token(email="renamed@example.com")
    with TestClient(app) as client:
        assert sign_in(client)[2].headers["location"] == "/#home"
        me = client.get("/api/auth/me").json()["user"]
    assert me["id"] == user.id
    # Password sign-in keeps working for the linked account.
    with TestClient(app) as client:
        assert (
            client.post(
                "/api/auth/login",
                json={"email": "customer@example.com", "password": PASSWORD},
            ).status_code
            == 200
        )


def test_link_requires_a_recent_login_and_matching_email(google, accounts, db):
    with TestClient(app) as client:
        assert (
            client.get(
                "/api/auth/google/start?link=true", follow_redirects=False
            ).headers["location"]
            == "/#login/google-relogin"
        )
        client.post(
            "/api/auth/login",
            json={"email": "customer@example.com", "password": PASSWORD},
        )
        assert sign_in(client, link=True)[2].headers["location"] == FAILED
        assert db.get(User, accounts["customer"].id).google_sub is None


def test_email_linked_to_another_google_account_is_refused(
    google, accounts, db
):
    accounts["customer"].google_sub = "someone-else"
    db.commit()
    google["token"] = id_token(email="customer@example.com")
    with TestClient(app) as client:
        assert sign_in(client)[2].headers["location"] == FAILED


@pytest.mark.parametrize(
    "token",
    [
        id_token(email_verified=False),
        id_token(aud="another-client"),
        id_token(iss="https://evil.example"),
        id_token(exp=int(time.time()) - 10),
        "not-a-jwt",
    ],
)
def test_untrusted_id_tokens_are_refused(google, token):
    google["token"] = token
    with TestClient(app) as client:
        *_, finished = sign_in(client)
        assert finished.headers["location"] == FAILED
        assert client.get("/api/auth/me").status_code == 401


def test_wrong_state_cancel_and_failed_exchange_are_refused(google):
    with TestClient(app) as client:
        *_, finished = sign_in(client, state="forged")
        assert finished.headers["location"] == FAILED
        *_, finished = sign_in(client, code="bad")
        assert finished.headers["location"] == FAILED
        cancelled = client.get(
            "/api/auth/google/callback",
            params={"error": "access_denied"},
            follow_redirects=False,
        )
        assert cancelled.headers["location"] == FAILED
        assert client.get("/api/auth/me").status_code == 401
    assert google["calls"] == [("bad", google["calls"][0][1])]


def test_google_only_account_cannot_use_password_login(google):
    with TestClient(app) as client:
        sign_in(client)
    with TestClient(app) as client:
        response = client.post(
            "/api/auth/login",
            json={"email": "person@example.com", "password": PASSWORD},
        )
    assert response.status_code == 401


def test_start_is_404_when_google_is_not_configured(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "")
    get_settings.cache_clear()
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/auth/google/start", follow_redirects=False
            )
    finally:
        get_settings.cache_clear()
    assert response.status_code == 404


def test_callback_without_state_or_cookie_is_refused(google):
    with TestClient(app) as client:
        # No /start: the browser has no g_oauth cookie.
        response = client.get(
            "/api/auth/google/callback",
            params={"code": "good", "state": "anything"},
            follow_redirects=False,
        )
        assert response.headers["location"] == FAILED
        started = client.get("/api/auth/google/start", follow_redirects=False)
        assert started.status_code == 302
        response = client.get(
            "/api/auth/google/callback",
            params={"code": "good"},
            follow_redirects=False,
        )
        assert response.headers["location"] == FAILED
        assert client.get("/api/auth/me").status_code == 401
    assert google["calls"] == []

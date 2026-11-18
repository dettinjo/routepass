from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from routepass.config import get_settings
from tests.conftest import AUTH


@pytest.fixture
def settings(monkeypatch):
    def apply(**env):
        for k, v in env.items():
            monkeypatch.setenv(f"ROUTEPASS_{k.upper()}", str(v))
        get_settings.cache_clear()

    return apply


def test_tailscale_identity_only_on_private_listener(client, settings):
    settings(allowed_emails="me@example.com", trust_tailscale_headers="true")
    me = {"Tailscale-User-Login": "me@example.com", "Tailscale-User-Name": "Me"}
    assert client.get("/api/v1/status", headers=me).status_code == 200
    assert (
        client.get("/api/v1/status", headers={"Tailscale-User-Login": "intruder@example.com"}).status_code
        == 401
    )
    who = client.get("/api/v1/auth/me", headers=me).json()
    assert who["authenticated"] and who["method"] == "tailscale" and who["email"] == "me@example.com"

    # The same request on the public listener (TestClient talks to port 80) is not trusted.
    settings(public_port=80)
    assert client.get("/api/v1/status", headers=me).status_code == 401
    assert client.post("/mcp", json={}, headers=me).status_code == 401
    assert client.get("/api/v1/status", headers=AUTH).status_code == 200
    assert client.get("/", headers=AUTH).status_code == 404  # no UI on the public listener
    assert client.get("/api/v1/auth/complete?code=x").status_code == 404


def test_tailscale_headers_ignored_unless_enabled(client, settings):
    settings(allowed_emails="me@example.com")
    assert client.get("/api/v1/status", headers={"Tailscale-User-Login": "me@example.com"}).status_code == 401


def test_token_login_sets_session_cookie(client, settings):
    settings(allowed_emails="me@example.com")
    assert client.post("/api/v1/auth/token-login", json={"token": "wrong"}).status_code == 401
    assert client.post("/api/v1/auth/token-login", json={"token": "test-token"}).status_code == 200
    assert client.get("/api/v1/status").status_code == 200  # cookie, no bearer
    client.post("/api/v1/auth/logout")
    assert client.get("/api/v1/status").status_code == 401


def test_google_sign_in_round_trip(client, settings, mock_apis):
    settings(
        allowed_emails="me@example.com",
        google_client_id="cid",
        google_client_secret="sec",
        public_url="https://public.example",
        base_url="https://private.example",
    )
    assert client.get("/api/v1/auth/me").json()["methods"]["google"] is True
    start = client.get("/api/v1/auth/google/start", follow_redirects=False)
    q = parse_qs(urlparse(start.headers["location"]).query)
    assert q["redirect_uri"] == ["https://public.example/api/v1/auth/google/callback"]

    mock_apis.post("https://oauth2.googleapis.com/token").mock(
        return_value=httpx.Response(200, json={"access_token": "at"})
    )
    userinfo = mock_apis.get("https://openidconnect.googleapis.com/v1/userinfo")
    userinfo.mock(
        return_value=httpx.Response(
            200, json={"email": "me@example.com", "email_verified": True, "name": "Me"}
        )
    )
    cb = client.get(f"/api/v1/auth/google/callback?code=c&state={q['state'][0]}", follow_redirects=False)
    target = urlparse(cb.headers["location"])
    assert target.netloc == "private.example" and target.path == "/api/v1/auth/complete"

    done = client.get(f"{target.path}?{target.query}", follow_redirects=False)
    set_cookie = done.headers.get("set-cookie", "")
    assert (
        done.status_code in (302, 307)
        and "rp_session" in set_cookie
        and "Secure" in set_cookie
        and "HttpOnly" in set_cookie
    )
    session = set_cookie.split(";", 1)[
        0
    ]  # the test client speaks http, so it would not resend a Secure cookie
    me = client.get("/api/v1/auth/me", headers={"Cookie": session}).json()
    assert me["authenticated"] and me["email"] == "me@example.com" and me["method"] == "google"

    assert client.get("/api/v1/status", headers={"Cookie": session}).status_code == 200

    # another Google account is turned away
    userinfo.mock(
        return_value=httpx.Response(200, json={"email": "else@example.com", "email_verified": True})
    )
    start = client.get("/api/v1/auth/google/start", follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    cb = client.get(f"/api/v1/auth/google/callback?code=c&state={state}", follow_redirects=False)
    assert "/login?error=" in cb.headers["location"]
    assert client.get("/api/v1/status").status_code == 401

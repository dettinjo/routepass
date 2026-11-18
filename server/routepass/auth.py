"""Sign-in for the web UI.

Three ways in, all for the allowed e-mail address(es) only:
  1. Tailscale identity — requests through `tailscale serve` carry `Tailscale-User-Login`; on the private
     listener (never the public one) a matching login is signed in without any click.
  2. Google — OAuth via the public URL's callback; the browser is handed back to the private UI with a
     one-time code, which becomes a session cookie there.
  3. The API token — kept for REST/MCP clients and as a fallback login.

Sessions are HMAC-signed cookies (no server-side state).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
from starlette.requests import HTTPConnection
from starlette.types import Scope

from routepass.config import get_settings
from routepass.security import token_ok

SESSION_COOKIE = "rp_session"
SESSION_DAYS = 180
GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"
CALLBACK_PATH = "/api/v1/auth/google/callback"


@dataclass
class Identity:
    email: str | None
    method: str  # token | session | tailscale | open
    name: str | None = None
    picture: str | None = None


# ── signing ──────────────────────────────────────────────────────────────────


def _key() -> bytes:
    from routepass.security import _fernet

    # Derive a separate MAC key from the credential-encryption key (never used for both purposes).
    return hashlib.sha256(b"routepass-session|" + _fernet()._signing_key).digest()


def sign(payload: dict[str, Any]) -> str:
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    mac = hmac.new(_key(), body.encode(), hashlib.sha256).hexdigest()[:40]
    return f"{body}.{mac}"


def unsign(value: str | None, max_age_s: int | None = None) -> dict[str, Any] | None:
    if not value or "." not in value:
        return None
    body, mac = value.rsplit(".", 1)
    if not hmac.compare_digest(mac, hmac.new(_key(), body.encode(), hashlib.sha256).hexdigest()[:40]):
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except ValueError:
        return None
    if payload.get("exp", 0) < time.time():
        return None
    if max_age_s is not None and payload.get("iat", 0) < time.time() - max_age_s:
        return None
    return payload


# ── policy ───────────────────────────────────────────────────────────────────


def allowed_emails() -> set[str]:
    return {e.strip().lower() for e in get_settings().allowed_emails.split(",") if e.strip()}


def email_allowed(email: str | None) -> bool:
    return bool(email) and email.lower() in allowed_emails()


def auth_disabled() -> bool:
    s = get_settings()
    return not s.api_token and not allowed_emails()


def is_public_listener(scope: Scope) -> bool:
    port = get_settings().public_port
    server = scope.get("server")
    return bool(port) and server is not None and server[1] == port


def google_configured() -> bool:
    s = get_settings()
    return bool(s.google_client_id and s.google_client_secret and s.public_url and allowed_emails())


def identify(conn: HTTPConnection) -> Identity | None:
    """Who is making this request (None = not signed in)."""
    public = is_public_listener(conn.scope)
    header = conn.headers.get("authorization", "")
    bearer = header[7:] if header.lower().startswith("bearer ") else conn.query_params.get("token")
    if bearer and get_settings().api_token and token_ok(bearer):
        return Identity(email=None, method="token")
    if auth_disabled() and not public:
        return Identity(email=None, method="open")
    if public:
        return None  # the internet-facing listener only accepts the API token
    session = unsign(conn.cookies.get(SESSION_COOKIE))
    if session and session.get("via") == "token":
        if session.get("tf") == token_fingerprint():
            return Identity(email=session.get("email"), method="token")
    elif session and email_allowed(session.get("email")):
        return Identity(
            email=session["email"],
            method=session.get("via", "session"),
            name=session.get("name"),
            picture=session.get("picture"),
        )
    if get_settings().trust_tailscale_headers:
        login = conn.headers.get("tailscale-user-login")
        if email_allowed(login):
            return Identity(
                email=login,
                method="tailscale",
                name=conn.headers.get("tailscale-user-name"),
                picture=conn.headers.get("tailscale-user-profile-pic"),
            )
    return None


def token_fingerprint() -> str:
    return hashlib.sha256(("rp|" + get_settings().api_token).encode()).hexdigest()[:16]


def session_cookie(identity: Identity) -> str:
    now = int(time.time())
    payload = {
        "email": identity.email,
        "name": identity.name,
        "picture": identity.picture,
        "via": identity.method,
        "iat": now,
        "exp": now + SESSION_DAYS * 86400,
    }
    if identity.method == "token":
        payload["tf"] = token_fingerprint()  # rotating the API token signs these sessions out
    return sign(payload)


def cookie_kwargs() -> dict[str, Any]:
    secure = get_settings().base_url.startswith("https://")
    return {
        "httponly": True,
        "secure": secure,
        "samesite": "lax",
        "max_age": SESSION_DAYS * 86400,
        "path": "/",
    }


# ── Google ───────────────────────────────────────────────────────────────────


def google_start_url() -> str:
    s = get_settings()
    state = sign({"n": secrets.token_urlsafe(8), "iat": int(time.time()), "exp": int(time.time()) + 600})
    query = urlencode(
        {
            "client_id": s.google_client_id,
            "redirect_uri": s.public_url.rstrip("/") + CALLBACK_PATH,
            "response_type": "code",
            "scope": "openid email profile",
            "prompt": "select_account",
            "state": state,
        }
    )
    return f"{GOOGLE_AUTH}?{query}"


class LoginError(Exception):
    pass


def google_finish(code: str, state: str) -> Identity:
    s = get_settings()
    if not unsign(state):
        raise LoginError("The sign-in link expired — please try again.")
    try:
        tok = httpx.post(
            GOOGLE_TOKEN,
            data={
                "client_id": s.google_client_id,
                "client_secret": s.google_client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": s.public_url.rstrip("/") + CALLBACK_PATH,
            },
            timeout=20,
        )
        tok.raise_for_status()
        info = httpx.get(
            GOOGLE_USERINFO, headers={"Authorization": f"Bearer {tok.json()['access_token']}"}, timeout=20
        )
        info.raise_for_status()
    except (httpx.HTTPError, KeyError) as exc:
        raise LoginError(f"Google sign-in failed: {exc}") from exc
    data = info.json()
    email = data.get("email")
    if not data.get("email_verified") or not email_allowed(email):
        raise LoginError(f"{email or 'This account'} is not allowed to use this RoutePass.")
    return Identity(email=email, method="google", name=data.get("name"), picture=data.get("picture"))


def handoff_code(identity: Identity) -> str:
    """Short-lived code carrying the identity from the public callback to the private UI host."""
    now = int(time.time())
    return sign(
        {
            "email": identity.email,
            "name": identity.name,
            "picture": identity.picture,
            "via": identity.method,
            "iat": now,
            "exp": now + 120,
            "handoff": True,
        }
    )


def redeem_handoff(code: str) -> Identity | None:
    data = unsign(code)
    if not data or not data.get("handoff") or not email_allowed(data.get("email")):
        return None
    return Identity(
        email=data["email"],
        method=data.get("via", "google"),
        name=data.get("name"),
        picture=data.get("picture"),
    )

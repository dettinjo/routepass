from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

import httpx
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.core import security
from app.core.config import settings
from app.db.models.subscription import Subscription
from app.db.models.user import StravaApp, StravaToken, User
from app.services.audit import write_audit

UTC = UTC

router = APIRouter(tags=["auth"])


class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str | None = None


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class StravaCallback(BaseModel):
    code: str


@router.post("/register", response_model=TokenResponse)
async def register_user(
    payload: RegisterRequest,
    request: Request,
    db: AsyncSession = Depends(deps.get_db),
) -> TokenResponse:
    """Create a new user account and issue an access token."""
    existing_result = await db.execute(select(User).where(User.email == payload.email))
    existing_user = existing_result.scalar_one_or_none()
    if existing_user is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Email is already registered.")

    # Self-hosted: enforce the operator-configured user cap (MAX_USERS > 0).
    if settings.DEPLOYMENT_MODE == "selfhosted" and settings.MAX_USERS > 0:
        from sqlalchemy import func

        count_result = await db.execute(select(func.count()).select_from(User))
        if (count_result.scalar() or 0) >= settings.MAX_USERS:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This instance has reached its maximum user limit.",
            )

    user = User(
        email=payload.email,
        password_hash=security.hash_password(payload.password),
        name=payload.name or None,
        is_active=True,
    )
    db.add(user)

    subscription = Subscription(
        user=user,
        tier="free",
        status="active",
    )
    db.add(subscription)
    await db.commit()
    await write_audit(db, user.id, "account_created", request)
    await db.commit()

    access_token = security.create_access_token(str(user.id))
    return TokenResponse(access_token=access_token)


@router.post("/login", response_model=TokenResponse)
async def login_user(
    payload: LoginRequest,
    db: AsyncSession = Depends(deps.get_db),
) -> TokenResponse:
    """Authenticate a user by email/password and issue an access token."""
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    if (
        user is None
        or not user.password_hash
        or not security.verify_password(payload.password, user.password_hash)
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password.")

    if not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User account is inactive.")

    user.last_login_at = datetime.now(UTC)
    await db.commit()

    access_token = security.create_access_token(str(user.id))
    return TokenResponse(access_token=access_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_access_token(
    user: User = Depends(deps.get_current_user),
) -> TokenResponse:
    """Issue a fresh access token for the authenticated user."""
    access_token = security.create_access_token(str(user.id))
    return TokenResponse(access_token=access_token)


@router.get("/me")
async def get_current_user_profile(
    user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_db),
) -> dict:
    """Retrieve the current logged-in user profile and connection statuses."""
    sub_result = await db.execute(select(Subscription).where(Subscription.user_id == user.id))
    sub = sub_result.scalar_one_or_none()
    tier = sub.tier if sub else "free"

    # Self-hosted instances unlock every Pro feature server-side (see require_tier),
    # so report the effective tier as "pro" to keep the UI consistent with that.
    if settings.DEPLOYMENT_MODE == "selfhosted" and tier == "free":
        tier = "pro"

    # Operator-comped accounts (ADMIN_EMAILS) report the top tier in cloud mode too.
    from app.core.tiers import is_comp_email

    if is_comp_email(user.email):
        tier = "business"

    from app.db.models.connection import Connection as ConnectionModel
    from app.db.models.user import StravaToken

    connections_result = await db.execute(
        select(ConnectionModel).where(ConnectionModel.user_id == user.id)
    )
    connected_platforms = {c.platform for c in connections_result.scalars().all()}
    strava_token = (
        await db.execute(select(StravaToken).where(StravaToken.user_id == user.id))
    ).scalar_one_or_none()
    if strava_token:
        connected_platforms.add("strava")

    return {
        "id": str(user.id),
        "email": user.email,
        "name": user.name,
        "is_active": user.is_active,
        "tier": tier,
        "connections": [{"platform": p, "connected": True} for p in sorted(connected_platforms)],
        # Legacy fields retained for backward-compatibility until frontend is updated (F3).
        "komoot_connected": "komoot" in connected_platforms,
        "strava_connected": "strava" in connected_platforms,
    }


@router.get("/strava/login")
async def get_strava_login_url(
    user: User = Depends(deps.get_current_user),
) -> dict:
    """Return the Strava OAuth URL. Frontend calls this (with Bearer token) then redirects."""
    # Encode a short-lived JWT as the state so the callback can identify the user
    # without requiring an auth header (Strava GET redirect has no header support).
    state_token = security.create_access_token(str(user.id), expires_delta=timedelta(minutes=10))
    redirect_uri = f"{settings.FRONTEND_URL}/strava/callback"
    url = (
        "https://www.strava.com/oauth/authorize"
        f"?client_id={settings.STRAVA_CLIENT_ID}"
        "&response_type=code"
        f"&redirect_uri={redirect_uri}"
        "&approval_prompt=force"
        "&scope=activity:write,activity:read_all"
        f"&state={state_token}"
    )
    return {"url": url, "state": state_token}


@router.post("/strava/callback")
async def strava_oauth_callback(
    payload: StravaCallback,
    request: Request,
    user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_db),
) -> dict:
    """Exchange OAuth code for Strava tokens and save to user profile."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://www.strava.com/oauth/token",
                data={
                    "client_id": settings.STRAVA_CLIENT_ID,
                    "client_secret": settings.STRAVA_CLIENT_SECRET,
                    "code": payload.code,
                    "grant_type": "authorization_code",
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Strava authentication failed: {exc}",
        ) from exc

    athlete_id = int(data["athlete"]["id"])

    # Pick the least-loaded Strava app to spread OAuth tokens across the app pool.
    from app.core.rate_limit import rate_limit_guard as _rlg

    apps_result = await db.execute(
        select(StravaApp).where(StravaApp.is_active == True)  # noqa: E712
    )
    all_apps = apps_result.scalars().all()
    if not all_apps:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "No Strava app configured. Contact the administrator.",
        )
    app_ids = [a.id for a in all_apps]
    chosen_app_id = await _rlg.pick_least_loaded_app(app_ids)
    strava_app = next((a for a in all_apps if a.id == chosen_app_id), all_apps[0])

    # Async SQLAlchemy does not support lazy loading, so user.strava_token is
    # always None. Explicitly query by user_id and also by athlete_id to handle
    # reconnects correctly without hitting the unique constraint.
    token_result = await db.execute(select(StravaToken).where(StravaToken.user_id == user.id))
    existing_token = token_result.scalar_one_or_none()

    if existing_token is None:
        # Also check if this athlete_id already exists under another user row
        # (e.g. a previous failed connect that left an orphaned record).
        orphan_result = await db.execute(
            select(StravaToken).where(StravaToken.strava_athlete_id == athlete_id)
        )
        existing_token = orphan_result.scalar_one_or_none()
        if existing_token is not None:
            # Re-assign the orphaned token to this user
            existing_token.user_id = user.id

    if existing_token is not None:
        existing_token.strava_app_id = strava_app.id
        existing_token.strava_athlete_id = athlete_id
        existing_token.access_token = security.encrypt(data["access_token"])
        existing_token.refresh_token = security.encrypt(data["refresh_token"])
        existing_token.expires_at = datetime.fromtimestamp(data["expires_at"], tz=UTC)
    else:
        db.add(
            StravaToken(
                user_id=user.id,
                strava_app_id=strava_app.id,
                strava_athlete_id=athlete_id,
                access_token=security.encrypt(data["access_token"]),
                refresh_token=security.encrypt(data["refresh_token"]),
                expires_at=datetime.fromtimestamp(data["expires_at"], tz=UTC),
                connected_at=datetime.now(UTC),
            )
        )

    # Keep the connections table in sync so the connections page shows Strava as connected
    from app.db.models.connection import Connection as ConnectionModel

    athlete_name = (data.get("athlete") or {}).get("username") or f"athlete_{athlete_id}"
    conn_result = await db.execute(
        select(ConnectionModel).where(
            ConnectionModel.user_id == user.id,
            ConnectionModel.platform == "strava",
        )
    )
    existing_conn = conn_result.scalar_one_or_none()
    if existing_conn:
        existing_conn.display_name = athlete_name
        existing_conn.status = "active"
    else:
        db.add(
            ConnectionModel(
                user_id=user.id,
                platform="strava",
                display_name=athlete_name,
                status="active",
            )
        )

    await write_audit(db, user.id, "strava_connected", request, {"athlete_id": athlete_id})
    await db.commit()
    return {"status": "success", "message": "Strava account connected"}


@router.delete("/strava/disconnect")
async def disconnect_strava(
    request: Request,
    user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_db),
) -> dict:
    """Remove the current Strava connection."""
    result = await db.execute(select(StravaToken).where(StravaToken.user_id == user.id))
    token = result.scalar_one_or_none()
    if token is not None:
        await db.delete(token)
    await write_audit(db, user.id, "strava_disconnected", request)
    await db.commit()
    return {"status": "success", "message": "Strava account disconnected"}


@router.delete("/komoot/disconnect")
async def disconnect_komoot(
    request: Request,
    user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_db),
) -> dict:
    """Remove the Komoot Connection record for the current user."""
    from app.db.models.connection import Connection as ConnectionModel

    existing = (
        await db.execute(
            select(ConnectionModel).where(
                ConnectionModel.user_id == user.id,
                ConnectionModel.platform == "komoot",
            )
        )
    ).scalar_one_or_none()
    if existing:
        await db.delete(existing)
    await write_audit(db, user.id, "komoot_disconnected", request)
    await db.commit()
    return {"status": "success", "message": "Komoot account disconnected"}


# ── Social auth helpers ────────────────────────────────────────────────────────

_STATE_COOKIE = "oauth_state"
_STATE_MAX_AGE = 600  # 10 minutes


def _set_state_cookie(response: Response) -> str:
    state = secrets.token_urlsafe(16)
    response.set_cookie(
        _STATE_COOKIE,
        state,
        max_age=_STATE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=settings.ENVIRONMENT == "production",
    )
    return state


def _validate_state(state: str, cookie_state: str | None) -> None:
    if not cookie_state or not secrets.compare_digest(state, cookie_state):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid OAuth state.")


async def _find_or_create_user(
    db: AsyncSession,
    email: str,
    name: str | None = None,
) -> User:
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(email=email, name=name, is_active=True)
        db.add(user)
        sub = Subscription(user=user, tier="free", status="active")
        db.add(sub)
        await db.commit()
    elif name and not user.name:
        # Backfill name on first social login if missing
        user.name = name
        await db.commit()
    return user


def _auth_redirect(token: str) -> RedirectResponse:
    url = f"{settings.FRONTEND_URL}/callback?token={token}"
    response = RedirectResponse(url, status_code=302)
    response.delete_cookie(_STATE_COOKIE)
    return response


# ── Google OAuth ───────────────────────────────────────────────────────────────


@router.get("/google", include_in_schema=False)
async def google_login() -> RedirectResponse:
    redirect_uri = f"{settings.FRONTEND_URL.rstrip('/')}/api/v1/auth/google/callback"
    response = RedirectResponse("", status_code=302)
    state = _set_state_cookie(response)
    url = (
        "https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={settings.GOOGLE_CLIENT_ID}"
        "&response_type=code"
        f"&redirect_uri={redirect_uri}"
        "&scope=openid%20email"
        f"&state={state}"
    )
    response.headers["location"] = url
    return response


@router.get("/google/callback", include_in_schema=False)
async def google_callback(
    code: str,
    state: str,
    db: AsyncSession = Depends(deps.get_db),
    cookie_state: str | None = Cookie(None, alias=_STATE_COOKIE),
) -> RedirectResponse:
    _validate_state(state, cookie_state)
    redirect_uri = f"{settings.FRONTEND_URL.rstrip('/')}/api/v1/auth/google/callback"
    try:
        async with httpx.AsyncClient() as client:
            token_resp = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
            token_resp.raise_for_status()
            user_resp = await client.get(
                "https://openidconnect.googleapis.com/v1/userinfo",
                headers={"Authorization": f"Bearer {token_resp.json()['access_token']}"},
            )
            user_resp.raise_for_status()
    except Exception as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Google auth failed: {exc}") from exc

    profile = user_resp.json()
    email: str = profile.get("email", "")
    if not email:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Google did not return an email.")
    name: str | None = profile.get("name") or profile.get("given_name")

    user = await _find_or_create_user(db, email, name=name)
    token = security.create_access_token(str(user.id))
    return _auth_redirect(token)


# ── GitHub OAuth ───────────────────────────────────────────────────────────────


@router.get("/github", include_in_schema=False)
async def github_login() -> RedirectResponse:
    redirect_uri = f"{settings.FRONTEND_URL.rstrip('/')}/api/v1/auth/github/callback"
    response = RedirectResponse("", status_code=302)
    state = _set_state_cookie(response)
    url = (
        "https://github.com/login/oauth/authorize"
        f"?client_id={settings.GITHUB_CLIENT_ID}"
        f"&redirect_uri={redirect_uri}"
        "&scope=user%3Aemail"
        f"&state={state}"
    )
    response.headers["location"] = url
    return response


@router.get("/github/callback", include_in_schema=False)
async def github_callback(
    code: str,
    state: str,
    db: AsyncSession = Depends(deps.get_db),
    cookie_state: str | None = Cookie(None, alias=_STATE_COOKIE),
) -> RedirectResponse:
    _validate_state(state, cookie_state)
    redirect_uri = f"{settings.FRONTEND_URL.rstrip('/')}/api/v1/auth/github/callback"
    try:
        async with httpx.AsyncClient() as client:
            token_resp = await client.post(
                "https://github.com/login/oauth/access_token",
                headers={"Accept": "application/json"},
                data={
                    "client_id": settings.GITHUB_CLIENT_ID,
                    "client_secret": settings.GITHUB_CLIENT_SECRET,
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
            )
            token_resp.raise_for_status()
            access_token = token_resp.json().get("access_token", "")
            gh_headers = {
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
            }
            emails_resp = await client.get(
                "https://api.github.com/user/emails",
                headers=gh_headers,
            )
            emails_resp.raise_for_status()
            user_profile_resp = await client.get(
                "https://api.github.com/user",
                headers=gh_headers,
            )
            user_profile_resp.raise_for_status()
    except Exception as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"GitHub auth failed: {exc}") from exc

    primary = next(
        (e["email"] for e in emails_resp.json() if e.get("primary") and e.get("verified")),
        None,
    )
    if not primary:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "GitHub did not return a verified primary email."
        )
    gh_profile = user_profile_resp.json()
    gh_name: str | None = gh_profile.get("name") or gh_profile.get("login")

    user = await _find_or_create_user(db, primary, name=gh_name)
    token = security.create_access_token(str(user.id))
    return _auth_redirect(token)


# ── User settings ──────────────────────────────────────────────────────────────


class UserSettings(BaseModel):
    name: str | None = None


@router.patch("/me/settings")
async def update_user_settings(
    payload: UserSettings,
    user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_db),
) -> dict:
    """Update the current user's profile settings."""
    if payload.name is not None:
        user.name = payload.name.strip() or None
    await db.commit()
    return {"name": user.name}


@router.delete("/account", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    request: Request,
    user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_db),
) -> None:
    """Permanently delete the authenticated user's account and all associated data.

    Steps:
    1. Cancel active Stripe subscription (cloud mode only, non-fatal).
    2. Delete the User row — ON DELETE CASCADE handles all child rows.
    """
    import logging as _logging

    _logger = _logging.getLogger(__name__)

    # 1. Cancel Stripe subscription (non-fatal — deletion continues regardless)
    if settings.DEPLOYMENT_MODE == "cloud" and settings.STRIPE_SECRET_KEY:
        sub_result = await db.execute(select(Subscription).where(Subscription.user_id == user.id))
        sub = sub_result.scalar_one_or_none()
        if sub and sub.stripe_subscription_id:
            try:
                import stripe as _stripe

                _stripe.api_key = settings.STRIPE_SECRET_KEY
                _stripe.Subscription.delete(sub.stripe_subscription_id)
            except Exception as exc:
                _logger.warning("delete_account: Stripe cancellation failed: %s", exc)

    # 2. Purge GPX blobs from object storage before cascade delete (non-fatal).
    # Must happen before the DB row is gone so we can still query the keys.
    if settings.DEPLOYMENT_MODE == "cloud" or settings.STORAGE_BACKEND != "db":
        from app.db.models.sync import SyncedActivity
        from app.services.storage import StorageService

        keys_result = await db.execute(
            select(SyncedActivity.gpx_storage_key).where(
                SyncedActivity.user_id == user.id,
                SyncedActivity.gpx_storage_key.isnot(None),
            )
        )
        for (key,) in keys_result.all():
            try:
                await StorageService.delete_gpx(key)
            except Exception as exc:
                _logger.warning("delete_account: failed to purge storage key %s: %s", key, exc)

    # 3. Write audit BEFORE cascade delete (user_id set to NULL after delete via SET NULL FK)
    await write_audit(db, user.id, "account_deleted", request)

    # 4. Delete user row — ON DELETE CASCADE purges all child tables
    # (synced_activities, connections, sync_rules, subscriptions, api_keys, strava_tokens, …)
    # ON DELETE SET NULL keeps the audit row with user_id=NULL for compliance.
    await db.execute(delete(User).where(User.id == user.id))
    await db.commit()
    _logger.info("Account deleted for user %s", user.id)

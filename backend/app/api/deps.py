from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from datetime import UTC, datetime
from uuid import UUID

import redis.asyncio as aioredis
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader, OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.security import hash_api_key, verify_access_token
from app.db.models.subscription import ApiKey
from app.db.models.user import User
from app.db.session import get_db  # re-export

UTC = UTC

__all__ = [
    "get_db",
    "get_current_user",
    "require_tier",
    "require_admin",
    "get_current_api_key_user",
    "get_redis",
    "oauth2_scheme",
]

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

TIER_RANKS: dict = {"free": 0, "pro": 1, "lifetime": 1, "business": 2}

_redis_pool: aioredis.Redis | None = None


async def get_redis() -> AsyncGenerator:
    """Yield an aioredis connection from the shared pool."""
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    yield _redis_pool


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Validate the Bearer JWT and return the corresponding User.

    Raises HTTP 401 if the token is invalid, expired, or the user does not exist
    or is inactive.
    """
    user_id = verify_access_token(token)  # raises 401 on failure

    result = await db.execute(
        select(User).where(User.id == UUID(user_id)).options(selectinload(User.strava_token))
    )
    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    """Return the current user if they may administer the instance.

    Self-hosted instances are single-owner, so any active user is treated as admin
    (mirrors require_tier unlocking all features). In cloud mode, User.is_admin is
    required. Raises HTTP 403 otherwise.
    """
    if settings.DEPLOYMENT_MODE == "selfhosted" or user.is_admin:
        return user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Admin access required.",
    )


def require_tier(min_tier: str) -> Callable:
    """Return a FastAPI dependency that raises HTTP 402 when the user's tier is insufficient.

    In self-hosted mode all features are unlocked regardless of tier, so the
    check is skipped entirely.

    Args:
        min_tier: Minimum required tier name ("free", "pro", or "business").
    """
    required_rank = TIER_RANKS.get(min_tier, 0)

    async def _check(
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> None:
        # Self-hosted: all features unlocked for the instance owner.
        if settings.DEPLOYMENT_MODE == "selfhosted":
            return

        from app.db.models.subscription import Subscription

        result = await db.execute(select(Subscription).where(Subscription.user_id == user.id))
        subscription = result.scalar_one_or_none()

        tier = subscription.tier if subscription else "free"
        if TIER_RANKS.get(tier, 0) < required_rank:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"This feature requires a {min_tier} subscription or higher.",
            )

    return _check


async def get_current_api_key_user(
    api_key: str = Security(api_key_header),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Validate an API key from the X-API-Key header and return the owner User.

    Raises HTTP 401 if the key is missing, invalid, revoked, or expired.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing API key",
        headers={"WWW-Authenticate": "ApiKey"},
    )

    if not api_key:
        raise credentials_exception

    key_hash = hash_api_key(api_key)
    result = await db.execute(select(ApiKey).where(ApiKey.key_hash == key_hash))
    api_key_record = result.scalar_one_or_none()

    if api_key_record is None:
        raise credentials_exception
    if api_key_record.revoked_at is not None:
        raise credentials_exception
    if api_key_record.expires_at is not None and api_key_record.expires_at < datetime.now(UTC):
        raise credentials_exception

    result = await db.execute(select(User).where(User.id == api_key_record.user_id))
    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        raise credentials_exception

    return user

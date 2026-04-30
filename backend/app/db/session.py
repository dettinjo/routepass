from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

_db_url = settings.DATABASE_URL
_engine_kwargs: dict = {"pool_pre_ping": True}

# SQLite (used in tests) does not support pool_size / max_overflow or
# prepared_statement_cache_size. Apply tuning only for real Postgres.
if not _db_url.startswith("sqlite"):
    _engine_kwargs["pool_size"] = settings.DB_POOL_SIZE
    _engine_kwargs["max_overflow"] = settings.DB_MAX_OVERFLOW
    _engine_kwargs["pool_timeout"] = settings.DB_POOL_TIMEOUT
    # Required for pgBouncer transaction-pool mode — disable prepared statements
    # so that connections can be returned to the pool mid-transaction.
    _engine_kwargs["connect_args"] = {"prepared_statement_cache_size": 0}

engine = create_async_engine(_db_url, **_engine_kwargs)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async database session.

    Automatically rolls back on unhandled exceptions and always closes
    the session when the request finishes.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise

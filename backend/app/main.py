from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

try:
    from scalar_fastapi import get_scalar_api_reference as _get_scalar_api_reference

    def get_scalar_api_reference(*args, **kwargs):  # type: ignore[misc]
        return _get_scalar_api_reference(*args, **kwargs)

except ImportError:
    get_scalar_api_reference = None  # type: ignore[assignment]

from sqlalchemy import select

from app.core.config import settings

logger = logging.getLogger(__name__)


async def _bootstrap_strava_app() -> None:
    """Ensure at least one StravaApp row exists, creating one from env vars if not."""
    from app.core import security
    from app.db.models.user import StravaApp
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(StravaApp).limit(1))
        if result.scalar_one_or_none() is not None:
            return

        logger.info("No StravaApp found — seeding default app from env vars.")
        app_entry = StravaApp(
            client_id=settings.STRAVA_CLIENT_ID,
            client_secret=security.encrypt(settings.STRAVA_CLIENT_SECRET),
            display_name="Default Strava App",
            is_active=True,
        )
        db.add(app_entry)
        await db.commit()
        logger.info("Default StravaApp created.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    app.state.redis = redis_client

    try:
        import arq

        arq_pool = await arq.create_pool(arq.connections.RedisSettings.from_dsn(settings.REDIS_URL))
        app.state.arq_pool = arq_pool
    except Exception:
        app.state.arq_pool = None

    try:
        await _bootstrap_strava_app()
    except Exception as exc:
        logger.warning("StravaApp bootstrap failed (non-fatal): %s", exc)

    yield

    await redis_client.aclose()
    if app.state.arq_pool is not None:
        await app.state.arq_pool.aclose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="RoutePass API",
        version="1.0.0",
        description=(
            "Middleware for fitness activity data. Connect sources (Komoot, Garmin, Polar), "
            "connect destinations (Strava, Intervals.icu, Runalyze), define sync rules — "
            "and your activities flow automatically."
        ),
        contact={"name": "RoutePass", "url": "https://routepass.online"},
        license_info={
            "name": "AGPL-3.0",
            "url": "https://www.gnu.org/licenses/agpl-3.0.html",
        },
        openapi_tags=[
            {"name": "auth", "description": "Authentication — register, login, OAuth connections"},
            {
                "name": "sync",
                "description": "Sync control — status, manual trigger, history rebuild",
            },
            {"name": "activities", "description": "Synced activity history and GPX download"},
            {"name": "rules", "description": "Sync rules — filter and transform activities (Pro+)"},
            {"name": "api-keys", "description": "API key management (Pro+)"},
            {"name": "billing", "description": "Stripe checkout, portal, and subscription status"},
            {"name": "webhooks", "description": "Inbound webhooks from Strava and Stripe"},
            {
                "name": "connections",
                "description": "Platform connections — Komoot, Strava, and more",
            },
            {
                "name": "pipelines",
                "description": "Sync pipelines — source → destination with rule chains",
            },
            {"name": "health", "description": "Health check"},
        ],
        # Disable default Swagger UI and ReDoc — Scalar replaces both at /docs when available
        docs_url=None if get_scalar_api_reference else "/docs",
        redoc_url=None,
        lifespan=lifespan,
    )

    if settings.ENVIRONMENT == "development":
        allow_origins = ["*"]
    elif settings.FRONTEND_URLS:
        # Support multiple origins (apex domain + app subdomain + custom self-hosted domains)
        allow_origins = [o.strip() for o in settings.FRONTEND_URLS.split(",") if o.strip()]
    else:
        allow_origins = [settings.FRONTEND_URL]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", tags=["health"])
    async def health_check():
        return {"status": "ok"}

    if get_scalar_api_reference:

        @app.get("/docs", include_in_schema=False)
        async def scalar_docs():
            return get_scalar_api_reference(
                openapi_url="/openapi.json",
                title="RoutePass API Reference",
                dark_mode=True,
            )

    from app.api.v1.router import router as api_v1_router

    app.include_router(api_v1_router, prefix="/api/v1")

    return app


app = create_app()

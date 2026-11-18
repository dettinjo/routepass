from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import HTTPConnection
from starlette.types import ASGIApp, Receive, Scope, Send

from routepass import __version__, auth
from routepass.api.routes import public, router
from routepass.config import get_settings
from routepass.db import init_db
from routepass.engine import runner
from routepass.mcp_server import mcp

STATIC_DIR = Path(__file__).parent / "static"


PUBLIC_PREFIXES = ("/api/v1/", "/mcp")


class AccessGate:
    """MCP needs a signed-in identity or the API token; the public listener serves API paths only."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            path = scope["path"]
            if auth.is_public_listener(scope) and not path.startswith(PUBLIC_PREFIXES):
                await JSONResponse({"detail": "Not found"}, status_code=404)(scope, receive, send)
                return
            if path.startswith("/mcp") and auth.identify(HTTPConnection(scope)) is None:
                await JSONResponse({"detail": "Missing or invalid API token"}, status_code=401)(
                    scope, receive, send
                )
                return
        await self.app(scope, receive, send)


def create_app(*, start_scheduler: bool = True) -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    init_db()
    from routepass.db import session_scope
    from routepass.engine.ingest import remap_sports_if_needed

    with session_scope() as db:
        remap_sports_if_needed(db)

    mcp_app = mcp.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if start_scheduler:
            runner.start_scheduler()
        async with mcp.session_manager.run():
            yield
        runner.stop_scheduler()

    app = FastAPI(
        title="RoutePass",
        version=__version__,
        description="Strava ⇄ Komoot sync with deduplicated activity analysis. MCP endpoint: /mcp",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(AccessGate)
    app.include_router(public)
    app.include_router(router)
    app.router.routes.extend(mcp_app.routes)

    if STATIC_DIR.exists():
        app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")
        index = STATIC_DIR / "index.html"

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            candidate = STATIC_DIR / path
            if path and candidate.is_file() and STATIC_DIR in candidate.resolve().parents:
                return FileResponse(candidate)
            return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return app

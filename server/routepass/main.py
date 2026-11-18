from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from mcp.server.transport_security import TransportSecuritySettings
from starlette.types import ASGIApp, Receive, Scope, Send

from routepass import __version__
from routepass.api.routes import public, router
from routepass.config import get_settings
from routepass.db import init_db
from routepass.engine import runner
from routepass.mcp_server import mcp
from routepass.security import token_ok

STATIC_DIR = Path(__file__).parent / "static"


class McpAuth:
    """Bearer-token gate in front of the MCP endpoint."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"].startswith("/mcp"):
            headers = dict(scope.get("headers") or [])
            auth = headers.get(b"authorization", b"").decode()
            presented = auth[7:] if auth.lower().startswith("bearer ") else None
            if not token_ok(presented):
                resp = JSONResponse({"detail": "Missing or invalid API token"}, status_code=401)
                await resp(scope, receive, send)
                return
        await self.app(scope, receive, send)


def create_app(*, start_scheduler: bool = True) -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    init_db()

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
    app.add_middleware(McpAuth)
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

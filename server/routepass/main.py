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


UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def cross_site(scope: Scope) -> bool:
    """True when a browser says this request was started by another site.

    Browser sessions here are ambient (cookie or Tailscale identity), so a page on another site could
    otherwise make the browser call RoutePass with the user's identity. Browsers send `Origin` on
    cross-origin POST/PUT/PATCH/DELETE and WebSocket handshakes, and `Sec-Fetch-Site` on modern engines.
    Requests without those headers (API clients, Strava's webhook) are not affected."""
    headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers") or []}
    if headers.get("authorization", "").lower().startswith("bearer "):
        return False  # a custom header cannot be attached by another site without CORS approval
    if headers.get("sec-fetch-site") == "cross-site":
        return True
    origin = headers.get("origin")
    if not origin or origin == "null":
        return origin == "null"
    from urllib.parse import urlparse

    return urlparse(origin).netloc.lower() != headers.get("host", "").lower()


class AccessGate:
    """MCP needs a signed-in identity or the API token; the public listener serves API paths only;
    state-changing browser requests and WebSockets must come from RoutePass's own pages."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "websocket" and cross_site(scope):
            await send({"type": "websocket.close", "code": 4403})
            return
        if scope["type"] == "http":
            path = scope["path"]
            if scope["method"] in UNSAFE_METHODS and cross_site(scope):
                await JSONResponse({"detail": "Cross-site request refused"}, status_code=403)(
                    scope, receive, send
                )
                return
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
        from routepass.ai import coach

        if start_scheduler:
            runner.start_scheduler()
            coach.start()
        async with mcp.session_manager.run():
            yield
        runner.stop_scheduler()
        coach.stop()

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

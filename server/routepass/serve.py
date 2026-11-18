"""Run the app on the private port and, if ROUTEPASS_PUBLIC_PORT is set, on a second public port.

Both listeners share one app and process; the lifespan (scheduler, MCP session manager) runs once.
The public listener is meant for an internet-facing reverse proxy: API paths only, API token only,
and Tailscale identity headers are never trusted there.
"""

from __future__ import annotations

import asyncio

import uvicorn

from routepass.asgi import app
from routepass.config import get_settings


async def main() -> None:
    settings = get_settings()
    common = {
        "host": "0.0.0.0",
        "proxy_headers": True,
        "forwarded_allow_ips": "*",
        "log_level": settings.log_level.lower(),
    }
    servers = [uvicorn.Server(uvicorn.Config(app, port=settings.port, **common))]
    if settings.public_port:
        servers.append(
            uvicorn.Server(uvicorn.Config(app, port=settings.public_port, lifespan="off", **common))
        )
    await asyncio.gather(*(s.serve() for s in servers))


if __name__ == "__main__":
    asyncio.run(main())

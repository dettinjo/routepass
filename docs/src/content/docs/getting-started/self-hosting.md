---
title: Self-Hosting
description: Run the full RoutePass stack on your own server with Docker.
---

The full RoutePass stack (backend API + background worker + frontend dashboard) can be self-hosted for free. You bring your own Strava API credentials and Komoot polls from your own IP — no shared rate limits, no IP-block risk.

## Prerequisites

- Docker and Docker Compose installed
- A registered [Strava API application](https://www.strava.com/settings/api) (free)
- A server with at least 1 vCPU and 1 GB RAM (a €6/mo Hetzner CX11 works fine)

## Step 1 — Clone the repository

```bash
git clone https://github.com/dettinjo/routepass.git
cd routepass
```

## Step 2 — Configure environment variables

Copy the template and fill in your values:

```bash
cp .env.selfhosted.template .env
```

Required variables:

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection string (`postgresql+asyncpg://...`) |
| `REDIS_URL` | Redis connection string (`redis://redis:6379`) |
| `SECRET_KEY` | Random 32-byte string for JWT signing (`openssl rand -hex 32`) |
| `KOMOOT_ENCRYPTION_KEY` | Fernet key for credential encryption (`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`) |
| `STRAVA_CLIENT_ID` | From your Strava API application |
| `STRAVA_CLIENT_SECRET` | From your Strava API application |
| `FRONTEND_URL` | Public URL of your frontend (e.g. `https://routepass.yourdomain.com`) |
| `ENVIRONMENT` | Set to `production` |

Optional (for billing, if you want to charge your own users):

| Variable | Description |
|----------|-------------|
| `STRIPE_SECRET_KEY` | Stripe secret key |
| `STRIPE_WEBHOOK_SECRET` | Stripe webhook endpoint secret |

## Step 3 — Start the stack

```bash
docker compose up -d
```

This starts:
- `api` — FastAPI backend on port 8000
- `worker` — ARQ background worker (sync jobs, cron scheduler)
- `db` — PostgreSQL 16
- `redis` — Redis 7
- `frontend` — Next.js dashboard on port 3000

## Step 4 — Run migrations

```bash
docker compose exec api alembic upgrade head
```

## Step 5 — Register your Strava webhook

Strava requires you to register a webhook subscription so RoutePass receives push events when athletes upload activities. Run:

```bash
docker compose exec api python -c "
from app.services.strava import register_strava_webhook
import asyncio
asyncio.run(register_strava_webhook())
"
```

## Step 6 — Health check

```bash
curl http://localhost:8000/health
# → {"status": "ok"}
```

## Updating

```bash
git pull
docker compose pull
docker compose up -d
docker compose exec api alembic upgrade head
```

## Reverse proxy (recommended)

Put nginx or Caddy in front of both services. Example Caddyfile:

```
api.yourdomain.com {
  reverse_proxy localhost:8000
}

routepass.yourdomain.com {
  reverse_proxy localhost:3000
}
```

## License

The backend and frontend are licensed under **AGPL-3.0**. Personal and household use is unrestricted. Running it as a paid service for others requires either open-sourcing your modifications or purchasing a commercial exception license.

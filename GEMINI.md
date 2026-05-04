# RoutePass — Google Gemini Instructions

## Start of Every Session

Run before touching any code:

```bash
make status          # shows git state + last 5 commits
make check           # ruff lint + pytest — must stay green
```

Read in this order:
1. `AI_HANDOFF.md` — verified current state, test count, known risks
2. `CLAUDE.md` — project conventions, constraints, git rules
3. `backend/CLAUDE.md` — backend patterns, code templates, error codes

> `PROJECT.md` and `PROJECT_OVERVIEW.md` may be stale. Prefer `AI_HANDOFF.md` + source files.

---

## What This Project Is

A dual-mode sync tool:
- **Cloud SaaS** — multi-tenant FastAPI backend, users pay for Pro tier via Stripe
- **Self-hosted** — users run the Docker stack on their own server, all features free (AGPL)

The syncer connects Komoot (unofficial API, polling-based) to Strava (official API, webhook-capable).

---

## Active Codebase Location

```
backend/          FastAPI SaaS backend (the only thing you should edit)
legacy/           Old standalone script — frozen, do not touch
frontend/         Not started yet
```

All backend code lives under `backend/app/`. Alembic migrations in `backend/alembic/`.

---

## Dev Commands

```bash
make dev          # Start api + worker + postgres + redis via docker compose
make dev-stop     # Stop containers
make api          # FastAPI local dev server (uvicorn, hot reload)
make worker       # ARQ worker locally
make test         # pytest -v
make lint         # ruff format + ruff check
make format       # auto-fix formatting
make check        # lint + test (run before every PR)
make migrate      # alembic upgrade head
make migrate-gen  # generate migration: make migrate-gen name=your_description
make shell-db     # psql into dev database
```

---

## Core Architecture

| Layer | Tech |
|---|---|
| HTTP API | FastAPI (async) |
| DB ORM | SQLAlchemy 2.0 (`AsyncSession`) |
| Database | PostgreSQL via `asyncpg` |
| Job queue | ARQ + Redis |
| Encryption | Fernet (`cryptography`) |
| Auth | JWT Bearer tokens + SHA-256 API keys |
| Payments | Stripe |
| HTTP client | `httpx.AsyncClient` |
| Config | `pydantic-settings` BaseSettings |

---

## Hard Rules — Never Break These

| Rule | Why |
|---|---|
| All Strava calls go through `RateLimitGuard.call()` | Shared 1000 req/day limit across all cloud users — one bypass breaks everyone |
| Komoot + Strava credentials encrypted with Fernet before any DB write | User security; key never in DB |
| No blocking I/O in async handlers | Use `httpx.AsyncClient`, `redis.asyncio`, `asyncpg` only |
| Every protected endpoint needs `Depends(get_current_user)` | No unauthenticated access to user data |
| Pro-only features need `Depends(require_tier("pro"))` | Returns HTTP 402 for free-tier users |
| Free-tier sync suspended when daily Strava usage > 800 | 150 req reserved for Pro users |

---

## Code Patterns

### Standard endpoint
```python
@router.get("/resource")
async def get_resource(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Model).where(Model.user_id == user.id))
    return result.scalars().all()
```

### Pro-gated endpoint
```python
@router.post("/resource")
async def create_resource(
    user: User = Depends(get_current_user),
    _tier: None = Depends(require_tier("pro")),
    db: AsyncSession = Depends(get_db),
):
    ...
```

### Fernet encryption
```python
from app.core.security import get_fernet
encrypted = get_fernet().encrypt(plaintext.encode())
plaintext = get_fernet().decrypt(encrypted_bytes).decode()
```

### DB query patterns
```python
# Select one
result = await db.execute(select(User).where(User.id == user_id))
user = result.scalar_one_or_none()

# Insert
db.add(SyncRule(user_id=user.id, **data))
await db.commit()
await db.refresh(obj)

# Update
stmt = update(User).where(User.id == uid).values(**kw).returning(User)
updated = (await db.execute(stmt)).scalar_one()
await db.commit()
```

---

## HTTP Error Codes

| Situation | Code |
|---|---|
| Missing or invalid JWT | 401 |
| Insufficient tier | 402 |
| Wrong user's resource | 403 |
| Resource not found | 404 |
| Komoot or Strava API failure | 502 |

---

## Before You Touch These Areas — Stop and Validate

- **DB schema / Alembic** — compare `backend/app/db/models/` with `backend/alembic/versions/` before assuming they match
- **Auth flow** — read `backend/app/api/deps.py` and `backend/app/core/security.py` before changing anything
- **ARQ jobs** — read both `sync_jobs.py` and `worker.py`; the scheduler cron and the job function must stay in sync
- **Strava token refresh** — happens inside workers, not in HTTP handlers; check the existing path before duplicating

---

## Git Workflow

```
main          Protected — never commit directly
feature/xyz   New features
fix/xyz       Bug fixes
chore/xyz     Tooling/config/infra
```

Run `make check` (lint + tests pass) before opening a PR.

---

## Closing a Session

Update `AI_HANDOFF.md` → "Current Project State" section with:
- What changed and what files were modified
- Result of `make check` and current test count
- Anything left in an inconsistent or risky state

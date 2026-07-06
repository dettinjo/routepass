# RoutePass — OpenAI Codex Instructions

## Session Start Protocol

Run these three commands before writing any code:

```bash
make status          # git status + last 5 commits
make check           # ruff lint + pytest (must stay green)
```

Read in this order:
1. `AI_HANDOFF.md` — authoritative current state, all verified facts, test counts
2. `CLAUDE.md` — conventions, constraints, git workflow
3. `backend/CLAUDE.md` — backend patterns, code templates, error codes

> **Do not trust** `PROJECT.md` or `PROJECT_OVERVIEW.md` as ground truth — they may lag behind the code. Use `AI_HANDOFF.md` + the actual source files.

---

## Project Layout

```
legacy/       Old standalone sync script — FROZEN, do not modify or import from it
backend/      Active SaaS backend (FastAPI + PostgreSQL + Redis + ARQ)
frontend/     Not started yet
```

The entire active codebase is inside `backend/`. The root `app/` (legacy) is read-only history.

---

## Dev Commands (Makefile)

```bash
make dev          # docker compose up: api + worker + db + redis
make dev-stop     # stop those containers
make dev-logs     # follow api + worker logs
make api          # run FastAPI locally (uvicorn, hot reload)
make worker       # run ARQ worker locally
make test         # pytest -v
make lint         # ruff format --check + ruff check
make format       # ruff format + ruff check --fix (auto-fix)
make check        # lint + test together
make migrate      # alembic upgrade head
make migrate-gen  # alembic revision --autogenerate -m "$(name)"
make shell-db     # psql into dev database
make status       # git status + log
```

Always run `make check` after any backend change before concluding a session.

---

## Architecture in 60 Seconds

- **Multi-tenant FastAPI SaaS** — one Strava app shared across all cloud users
- **Auth**: JWT Bearer + SHA-256 API keys; all routes need `Depends(get_current_user)`
- **Tier gating**: `Depends(require_tier("pro"))` → HTTP 402 if insufficient
- **Strava calls**: MUST go through `RateLimitGuard.call()` — never call Strava directly
- **Credentials**: Komoot email/password and Strava tokens always Fernet-encrypted before DB write
- **Jobs**: ARQ workers (`poll_komoot_user`, `komoot_poll_scheduler`) — no sync logic in HTTP handlers
- **DB**: SQLAlchemy 2.0 async — `await db.execute(select(Model).where(...))`, `await db.commit()`

---

## Non-Negotiable Constraints

1. **No direct Strava calls** — all Strava HTTP traffic must go through `RateLimitGuard.call()`.
   Bypassing this breaks rate limits for *all* users sharing the app.

2. **No plaintext credentials** — encrypt with `get_fernet().encrypt()` before any DB write.
   Decrypt only in-memory inside a job or service.

3. **No blocking I/O** — all handlers and services are async. Use `httpx.AsyncClient`, never `requests`.

4. **Free tier budget** — suspend free-tier sync when daily Strava usage > 800 (150 req reserved for Pro).

5. **Komoot API is unofficial** — `api/v007` can change. Wrap all calls, fail gracefully with retry.

---

## Key File Locations

| What | Where |
|---|---|
| App factory + lifespan | `backend/app/main.py` |
| All settings/env vars | `backend/app/core/config.py` |
| JWT + Fernet utils | `backend/app/core/security.py` |
| Rate limit guard | `backend/app/core/rate_limit.py` |
| Auth dependencies | `backend/app/api/deps.py` |
| Route files | `backend/app/api/v1/*.py` |
| DB models | `backend/app/db/models/*.py` |
| Services | `backend/app/services/*.py` |
| ARQ workers | `backend/app/jobs/*.py` |
| Tests | `backend/tests/` |
| DB migrations | `backend/alembic/versions/` |

---

## Route Template

```python
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_current_user, get_db, require_tier
from app.db.models.user import User

router = APIRouter(prefix="/example", tags=["example"])

@router.get("/resource")
async def get_resource(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ...

@router.post("/pro-resource")
async def create_pro_resource(
    user: User = Depends(get_current_user),
    _tier: None = Depends(require_tier("pro")),  # raises 402 for free users
    db: AsyncSession = Depends(get_db),
):
    ...
```

---

## HTTP Error Codes

| Situation | Code |
|---|---|
| Missing/invalid JWT | 401 |
| Insufficient tier | 402 |
| Forbidden resource (wrong user) | 403 |
| Not found | 404 |
| External API failure (Strava/Komoot) | 502 |

---

## Git Workflow

```
main          Protected — never commit directly
feature/xyz   New features
fix/xyz       Bug fixes
chore/xyz     Infra, deps, tooling
```

Never push to `main` directly. Run `make check` before opening a PR.

---

## Session End Protocol

Before finishing a session, write a short summary to `AI_HANDOFF.md` under "Current Project State":
- What changed
- What was verified (`make check` result + test count)
- What remains risky or inconsistent

This keeps the handoff document accurate for the next AI session.

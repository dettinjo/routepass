# RoutePass — Claude Code Instructions

## Read Before Starting Any Session

1. `PROJECT.md` — project goals, status, implementation phases, business model, API constraints
2. `backend/CLAUDE.md` — compact backend architecture: code patterns, DB conventions, all route templates

## Project Layout

```
/app          Standalone self-hosted worker (MIT, Python, SQLite, APScheduler) — COMPLETE
/backend      SaaS multi-tenant backend (AGPL, FastAPI, PostgreSQL, Redis, ARQ) — IN PROGRESS
/frontend     Next.js dashboard — NOT STARTED
PROJECT.md    Living project overview. Update this when making architectural decisions.
```

## Dev Commands

```bash
make dev          # Start SaaS stack (API + DB + Redis + worker)
make dev-stop     # Stop SaaS stack
make dev-logs     # Follow API logs
make test         # Run backend tests (pytest)
make lint         # ruff + mypy
make check        # lint + test (run before every PR)
make migrate      # alembic upgrade head
make migrate-gen  # generate new migration (set name= first)
make shell-db     # psql into dev database
make standalone   # Start the simple /app standalone service
```

## Coding Conventions — Backend

- **Auth**: Every user-facing endpoint needs `user: User = Depends(get_current_user)`
- **Tier gates**: Premium features need `_: None = Depends(require_tier("pro"))` → raises 402
- **Strava calls**: ALL outbound Strava API calls MUST go through `RateLimitGuard.call()` — never call Strava directly
- **Encryption**: Komoot credentials and Strava tokens always via `encrypt()`/`decrypt()` from `app.core.security`
- **Async**: No blocking I/O in async handlers. Use `httpx.AsyncClient`, `asyncpg`, `redis.asyncio`
- **DB**: SQLAlchemy 2.0 async pattern — `await db.execute(select(Model).where(...))`, `await db.commit()`
- **Error codes**: 401 auth missing/invalid, 402 tier insufficient, 403 wrong resource, 404 not found, 502 external API failure
- **Comments**: Only when the WHY is non-obvious. No docstrings, no block comments explaining what the code does.
- **No backwards compat**: Don't add shims, unused vars, or removed-code comments. Delete cleanly.

## Git Workflow

```
main            Protected. Never commit directly.
feature/xyz     New features
fix/xyz         Bug fixes
chore/xyz       Infra, deps, config
```

Run `make check` before opening a PR. PRs go to `main` only via pull request.

## Critical Constraints — Never Violate

1. **Komoot API is unofficial** — `api/v007` can break. Keep client abstracted; fail gracefully with retry.
2. **Strava rate limit is shared** — 1000 req/day across all cloud users. One direct Strava call that bypasses `RateLimitGuard` can cascade and break all users.
3. **Never store plaintext credentials** — Komoot email/password and Strava tokens always encrypted with Fernet before DB write.
4. **Free tier budget** — suspend free-tier sync when daily Strava usage > 800 (150 reserved for Pro).
5. **Self-hosted users bring their own Strava app** — never mix self-hosted and cloud users in the same rate limit pool.

## Subagent Strategy

Use the **Explore** subagent for codebase searches spanning multiple files. Use the **Plan** subagent before implementing anything that touches the database schema, auth flow, or job queue. Ask the user before: committing, pushing, creating PRs, running docker compose down.

## Session Start Checklist

- [ ] Read PROJECT.md (especially "Implementation Status" and "Implementation Phases")
- [ ] Check `git status` and `git log --oneline -5`
- [ ] Run `make check` to confirm current baseline is passing

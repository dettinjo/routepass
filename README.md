# RoutePass

<p align="center">
  <img src="img/logo.webp" alt="RoutePass logo" width="300" />
</p>

RoutePass is a SaaS for bidirectional sync between Komoot and Strava. It features a multi-tenant FastAPI backend, automated rule evaluation, and a modern architecture designed for reliability and security.

## Current State

- `backend/`: active FastAPI + PostgreSQL + Redis + ARQ codebase (Python 3.9+)
- `frontend/`: active Next.js 15 App Router codebase (Dashboard, Landing, Auth)
- `legacy/`: old standalone single-user implementation kept for reference

The backend and frontend are complete with working API routes, background jobs, full test coverage, and a responsive UI.

## What Is Verified

- `make check` (linting + pytest) passes: **49 passed**
- Database schema applies successfully to a clean PostgreSQL 16 container
- Strava tokens are stored encrypted and refreshed automatically
- Rate limiting is strictly enforced via Redis-backed `RateLimitGuard`
- Bidirectional sync logic with rule engine is fully tested

## Quick Start

### 1. Create an env file

For backend development:

```bash
cp .env.saas.template .env.saas
```

For self-hosted-style backend runs:

```bash
cp .env.selfhosted.template .env.selfhosted
```

Fill in the required variables in `.env.saas`.

### 2. Start the backend stack

```bash
make dev
make dev-logs
```

This starts the `db`, `redis`, `api`, and `worker` services.

### 3. Run checks

```bash
make check
```

## Useful Commands

```bash
make status       # Git status + log
make dev          # Start docker stack
make dev-stop     # Stop docker stack
make test         # Run pytest
make lint         # Run ruff checks
make check        # lint + test
make migrate      # Run alembic migrations
```

## Architecture Notes

### Backend

- FastAPI async API
- SQLAlchemy 2.0 async ORM (PostgreSQL)
- Redis + ARQ workers for background jobs
- Strava calls guarded by `RateLimitGuard`
- Komoot and Strava credentials encrypted with AES-256 Fernet

### Important Constraints

- Komoot uses an unofficial API; all calls are wrapped for safe failure.
- Strava rate limits are shared per app and strictly managed.
- Reverse sync (Strava → Komoot) records metadata while waiting for a viable GPX upload path.

## Repository Documentation

- `AI_HANDOFF.md`: **Single Source of Truth** for current implementation state
- `CODEX.md`: Codex workflow and repo-specific guardrails
- `CLAUDE.md`: Claude-oriented project instructions
- `GEMINI.md`: Gemini-oriented project instructions
- `docs/setup_guide.md`: User account-linking guidance
- `docs/PROJECT_LEGACY.md`: Original product planning history

## License

See [LICENSE](LICENSE).

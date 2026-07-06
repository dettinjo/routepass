SHELL := /bin/zsh
COMPOSE_SAAS := docker compose --env-file .env.saas
COMPOSE_SELFHOSTED := docker compose --env-file .env.selfhosted
VENV_ACTIVATE := source backend/.venv/bin/activate

.PHONY: status dev dev-stop dev-logs api worker test lint format check migrate migrate-gen shell-db standalone pre-commit-install

status:
	git status --short
	git log --oneline -5

dev:
	$(COMPOSE_SAAS) up -d db redis api worker

dev-stop:
	$(COMPOSE_SAAS) stop api worker db redis

dev-logs:
	$(COMPOSE_SAAS) logs -f api worker

api:
	$(VENV_ACTIVATE) && cd backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

worker:
	$(VENV_ACTIVATE) && cd backend && python -m arq app.jobs.worker.WorkerSettings

test:
	$(VENV_ACTIVATE) && cd backend && python -m pytest tests/ -v

lint:
	$(VENV_ACTIVATE) && cd backend && ruff format --check . && ruff check .

format:
	$(VENV_ACTIVATE) && cd backend && ruff format . && ruff check --fix .

check: lint test

migrate:
	$(VENV_ACTIVATE) && cd backend && alembic upgrade heads

migrate-gen:
	$(VENV_ACTIVATE) && cd backend && alembic revision --autogenerate -m "$(name)"

shell-db:
	$(COMPOSE_SAAS) exec db psql -U postgres routepass

standalone:
	docker compose -f docker-compose.yml up -d

pre-commit-install:
	pre-commit install

# ── Frontend ──────────────────────────────────────────────────────────────────

frontend-install:
	cd frontend && npm install

frontend-dev:
	cd frontend && npm run dev

frontend-build:
	cd frontend && npm run build

frontend-check:
	cd frontend && npm run check

frontend-lint:
	cd frontend && npm run lint

frontend-typecheck:
	cd frontend && npm run typecheck

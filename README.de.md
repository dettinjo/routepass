# RoutePass

<!-- portfolio:date=2026-04-15 -->

[Deutsch](README.de.md) · [English](README.md)

<p align="center">
  <img src="img/logo.svg" alt="RoutePass-Logo" width="160" />
</p>

## Übersicht

RoutePass ist ein Sync-Hub für Fitness-Plattformen — verbinde Strava, Komoot, Garmin, Intervals.icu und mehr und leite jede neue Aktivität über konfigurierbare Pipelines und Regeln zwischen ihnen weiter.

Jede Plattform ist gleichberechtigt: Dieselbe Aktivität kann an mehrere Ziele verteilt werden, oder mehrere Quellen können in eine münden — pro Pipeline entscheiden Regeln (Sportart, Distanz, Höhenmeter, Name), was dabei transformiert, umbenannt oder übersprungen wird.

Entstanden ist RoutePass aus einem viel kleineren Werkzeug — einem einfachen Komoot→Strava-Sync-Skript — und hat sich zu einem Multi-Tenant-FastAPI-Backend mit Next.js-Dashboard, asynchronen Background-Workern und einer Regel-Engine entwickelt, die „Quelle" und „Ziel" als austauschbare Rollen behandelt statt als feste Richtungen.

<p align="center">
  <img src="docs/screenshots/dashboard.png" width="32%" />
  <img src="docs/screenshots/connections.png" width="32%" />
  <img src="docs/screenshots/pipelines.png" width="32%" />
</p>

## Funktionen

- **Jede Quelle, jedes Ziel** — Strava, Komoot und Intervals.icu/Runalyze/Garmin können jeweils als Quelle oder Ziel einer Pipeline dienen; keine feste Richtung fest verdrahtet.
- **Multi-Pipeline-Routing** — eine Quelle auf mehrere Ziele verteilen oder mehrere Quellen in eine zusammenführen, mit einer eigenen Regelkette pro Pipeline.
- **Regel-Engine** — Aktivitäten pro Pipeline nach Sportart, Distanz, Höhenmetern oder Name filtern und transformieren, bevor sie weitergeleitet werden.
- **Rate-Limit-sicher** — alle ausgehenden Strava-Aufrufe laufen über einen gemeinsamen, Redis-gestützten Rate-Limiter (`RateLimitGuard`), sodass ein einzelner vielbeschäftigter Nutzer nicht das API-Kontingent aller anderen aufbrauchen kann.
- **Privacy by Design** — Komoot-Zugangsdaten und Strava-Tokens werden verschlüsselt gespeichert (AES-256 Fernet); GPX-Downloads laufen über kurzlebige, vorsignierte URLs statt über die API gestreamt zu werden; DSGVO-Datenexport und Kontolöschung sind eingebaut, inklusive eines Audit-Logs, das die Kontolöschung zu Compliance-Zwecken überdauert.
- **Self-hostable** — MIT-lizenziert. `DEPLOYMENT_MODE=selfhosted` entfernt jegliche Billing-/Tier-Beschränkungen vollständig, sodass eine Einzelinstanz mit allen Funktionen läuft — mit der eigenen Strava-API-App.
- **REST-API + Webhooks** — programmatischer Zugriff über API-Keys, dazu ausgehende signierte Webhooks und eingehende Strava-Push-Events für Echtzeit-Sync statt Polling.

## Tech-Stack

**Backend** — FastAPI (async) · SQLAlchemy 2.0 (async, PostgreSQL) · Alembic · Redis + ARQ (Background-Jobs) · JWT-Auth · Fernet-Verschlüsselung

**Frontend** — Next.js 15 (App Router) · TypeScript · Tailwind CSS · React Query · Framer Motion

**Infra** — Docker Compose · Coolify · self-hosted auf Hetzner, diese Instanz läuft im Modus `selfhosted` als öffentliche Demo

## Ausprobieren

Die öffentliche Instanz unter [routepass.online](https://routepass.online) läuft mit dem `main`-Branch dieses Repos im Self-hosted-Modus: kostenlos registrieren, Strava verbinden und eine Pipeline einrichten. Billing-/Tier-Beschränkungen sind in dieser Demo deaktiviert — alle Funktionen sind freigeschaltet.

## Schnellstart (lokale Entwicklung)

### 1. Env-Datei anlegen

```bash
cp .env.saas.template .env.saas
```

Die erforderlichen Variablen ausfüllen (`SECRET_KEY`, `KOMOOT_ENCRYPTION_KEY`, `STRAVA_CLIENT_ID`/`STRAVA_CLIENT_SECRET` von einer [Strava-API-App](https://www.strava.com/settings/api)).

### 2. Stack starten

```bash
make dev       # api + worker + db + redis + frontend
make dev-logs
```

### 3. Checks ausführen

```bash
make check     # ruff + mypy + pytest
```

## Nützliche Befehle

```bash
make status       # Git-Status + Log
make dev          # Docker-Stack starten
make dev-stop     # Docker-Stack stoppen
make test         # Pytest ausführen
make lint         # Ruff-Checks ausführen
make check        # Lint + Test
make migrate      # Alembic-Migrationen ausführen
```

## Architektur-Hinweise

- FastAPI-Async-API mit SQLAlchemy 2.0 Async-ORM (PostgreSQL)
- Redis + ARQ-Worker für Background-Sync-Jobs (`poll_user_sources`, Watermarks pro Verbindung, Echtzeit-Ingestion von Strava-Webhooks)
- Alle ausgehenden Strava-Aufrufe laufen über `RateLimitGuard` (gemeinsames Kontingent, Multi-App-Fan-out)
- Komoots API ist inoffiziell und nicht per OAuth authentifiziert — Zugangsdaten werden mit AES-256 Fernet verschlüsselt, niemals im Klartext gespeichert
- GPX-Objektspeicher ist austauschbar: standardmäßig DB-Spalte (self-hosted), S3/R2-kompatibel für größere Deployments

## Repository-Dokumentation

- `AI_HANDOFF.md`: aktueller Implementierungsstand, Migrationskette, Testabdeckung
- `IMPLEMENTATION_PLAN.md`: vollständiger Launch-Plan (Skalierbarkeit, Deployment, Datenschutz, mehrdirektionaler Sync)
- `docs/setup_guide.md`: Anleitung zur Kontoverknüpfung für Nutzer
- `docs/PROJECT_LEGACY.md`: ursprüngliches Einzelnutzer-Tool, aus dem das Projekt entstanden ist

## Lizenz

MIT — siehe [LICENSE](LICENSE).

---
title: Data Handling
description: What RoutePass stores, how it is encrypted, and how to delete your data.
---

We built RoutePass on the assumption that fitness data is personal. This page documents exactly what we store, how we protect it, and how to remove it.

## What we store

| Data | Storage | Protection |
|------|---------|------------|
| Email address | PostgreSQL | Plaintext (used for login + notifications) |
| Password | PostgreSQL | bcrypt hash (we never store the plaintext) |
| Komoot email | PostgreSQL | AES-256 encrypted (Fernet) |
| Komoot password | PostgreSQL | AES-256 encrypted (Fernet) |
| Strava access token | PostgreSQL | AES-256 encrypted (Fernet) |
| Strava refresh token | PostgreSQL | AES-256 encrypted (Fernet) |
| Activity metadata | PostgreSQL | Plaintext (name, sport type, distance, elevation, duration) |
| Sync history | PostgreSQL | Plaintext (sync status, timestamps, error messages) |

## What we do NOT store

- **GPX files** — downloaded from Komoot, uploaded to Strava, then discarded. We never write them to disk or a database.
- **Full activity data beyond metadata** — we don't store heart rate, power, cadence, lap data, or GPS tracks.
- **Strava activity content** — once uploaded, we only retain the Strava activity ID for duplicate prevention.

## Encryption details

Komoot credentials and Strava tokens are encrypted using [Python's `cryptography` library](https://cryptography.io/) with Fernet symmetric encryption (AES-128-CBC + HMAC-SHA256). The encryption key is stored in the server environment (`KOMOOT_ENCRYPTION_KEY`), never in the database.

You can verify this in the source: [`backend/app/core/security.py`](https://github.com/dettinjo/routepass/blob/main/backend/app/core/security.py).

## API keys

API keys (Pro) are stored as SHA-256 hashes — we only retain the prefix for display (`rp_live_abc123...`). The raw key is shown once at creation and never retrievable again. Treat it like a password.

## Data retention

- **Active account** — all data retained while your account is active.
- **Cancelled subscription** — account downgraded to Free tier; Pro-only data (extra rules, API keys) is preserved but gated.
- **Deleted account** — all data permanently deleted within 30 days. Email [privacy@routepass.online](mailto:privacy@routepass.online) to request immediate deletion.

## Self-hosting

If you self-host, all data stays on your own PostgreSQL instance. We have no access to it.

---
title: Rate Limits
description: API rate limits for RoutePass and the upstream platforms it integrates with.
---

## RoutePass API

The RoutePass API itself has no published rate limit for normal use. Fair-use applies — automated scripts hammering the API will be throttled. If you need higher throughput for a specific use case, [contact us](mailto:support@routepass.online).

---

## Strava (shared pool)

This is the most important constraint in the system. Strava enforces:

- **100 requests per 15 minutes** per registered Strava app
- **1,000 requests per day** per registered Strava app

These limits are **shared across all RoutePass cloud users** using the same Strava app registration.

### Calls per activity sync

| Operation | Calls |
|-----------|-------|
| `POST /uploads` (GPX upload) | 1 |
| `GET /uploads/{id}` (poll until ready) | ~2–3 |
| `PUT /activities/{id}` (set metadata) | 1 |
| Token refresh (amortized) | ~0.1 |
| **Total per activity** | **~4–5** |

With 1,000 calls/day: approximately **200 activity syncs/day** across the entire shared pool.

### Priority queue

When the budget is tight, RoutePass applies this priority:

1. **Pro users** — always served first
2. **Free users** — suspended when daily usage exceeds 800 calls (150 reserved for Pro)

Self-hosted users have their own Strava app registration and are completely unaffected by this pool.

### Multi-app pooling (roadmap)

A second Strava app registration doubles the daily budget. The `strava_apps` table supports round-robin pooling across multiple apps — this is on the roadmap for when user growth demands it.

---

## Komoot (polling)

Komoot has no published rate limit. Empirically:
- Polling every 10 minutes per user is safe
- Sustained bursts from one IP may trigger temporary blocks

RoutePass mitigates this by staggering poll times across users with random jitter and distributing polls across multiple egress IPs at scale.

---

## Intervals.icu

- ~1 request per second per API key
- No published daily cap

RoutePass queues Intervals.icu pushes and respects the 1 req/sec limit.

---

## Runalyze

- 30 requests per minute per personal access token

RoutePass queues Runalyze uploads and respects the 30 req/min limit. Large backfills are spread over several minutes.

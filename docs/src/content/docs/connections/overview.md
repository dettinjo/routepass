---
title: Connections Overview
description: How sources, destinations, and pipelines work in RoutePass.
---

RoutePass organizes your integrations into three concepts: **sources**, **destinations**, and **pipelines**. At the centre is the **activity hub** — a single store of all your activities regardless of where they came from.

## The Activity Hub

Every activity from every connected source lands in the RoutePass activity hub. This is the authoritative record — you can see all your activities in one place, filtered and searchable, regardless of whether they came from Komoot, Strava, or a manual GPX import.

```
[Komoot]  ──┐
[Strava]  ──┤──► [RoutePass Hub] ──► [Strava]
[GPX]     ──┘                    ──► [Intervals.icu]
                                  ──► [Runalyze]
```

Ingestion is **idempotent** — the same activity arriving twice (e.g. via webhook and then backfill) is stored only once, enforced by unique constraints at the database level.

## Sources

A source is a platform that RoutePass **pulls activity data from**. When you record an activity on a source platform, RoutePass detects it and stores it in the hub.

Sources are ingested in two ways depending on the platform:

- **Webhook push (real-time):** Strava sends a push notification when an activity is created. RoutePass processes it immediately.
- **Polling (scheduled):** Komoot has no webhooks, so RoutePass polls periodically for new tours using a watermark (last sync timestamp) to fetch only new activity since the last check.

Poll intervals vary by tier:

| Tier | Poll interval |
|------|--------------|
| Free | ~2 hours (batched with other users) |
| Pro | ~10 minutes |

**Currently supported sources:** Komoot, Strava

## Destinations

A destination is a platform that **receives activities** after RoutePass processes them. You can have multiple destinations — RoutePass pushes to all connected destinations that match the pipeline rules.

**Currently supported destinations:** Strava, Intervals.icu, Runalyze

:::note
Strava is both a source and a destination. Activities you record on Strava are ingested into the hub; activities from Komoot or GPX imports can be uploaded to your Strava feed.
:::

## Pipelines

A **pipeline** connects one source to one destination and has its own independent rule chain.

```
[Komoot source] ──► [Rule chain A] ──► [Strava destination]
[Komoot source] ──► [Rule chain B] ──► [Intervals.icu destination]
```

This means you can, for example:
- Send all Komoot activities to Strava (no filter)
- Send only Komoot runs over 5 km to Intervals.icu
- Skip all yoga sessions from reaching any destination

Each rule chain is evaluated independently. Rules on pipeline A don't affect pipeline B.

## Sync trigger

The activity hub refreshes automatically in the background on a cron schedule. You can also trigger an immediate sync:

- **Dashboard → Refresh button** — triggers a sync and refreshes the activity list after 5 seconds
- **`POST /api/v1/sync/trigger`** — API trigger (Pro with API key)

## Connecting a platform

All connections are managed from **Dashboard → Connections**.

- For **OAuth platforms** (Strava): click Connect, authorize on the platform's OAuth page, get redirected back.
- For **credential-based platforms** (Komoot): enter your email and password. Credentials are encrypted immediately with AES-256 before storage.
- For **API key platforms** (Intervals.icu, Runalyze): paste your personal API key or token.

## Disconnecting

Click **Disconnect** next to any connection. This removes the credentials from our database. Any pipelines using that connection are paused until you reconnect.

## Platform pages

- [Komoot](/connections/komoot/) — email/password, polling, limitations
- [Strava](/connections/strava/) — OAuth, webhook, bidirectional sync, GPS streams
- [Intervals.icu](/connections/intervals-icu/) — API key, athlete ID
- [Runalyze](/connections/runalyze/) — personal access token

---
title: Komoot
description: Connecting Komoot as a source platform in RoutePass.
---

Komoot is the primary source platform. RoutePass polls your Komoot account for new tours and pushes them to your connected destinations.

## Connecting

1. Go to **Connections → Sources → Connect Komoot**.
2. Enter your Komoot email address and password.
3. Click **Save**.

RoutePass immediately verifies the credentials by fetching your tour list, then begins the initial history sync.

## How credentials are stored

Komoot requires HTTP Basic Auth — there is no OAuth. Your email and password are:

1. Received over HTTPS (never in the clear)
2. Immediately encrypted with AES-256 (Fernet) using a server-side key
3. Written to the database as ciphertext only

The encryption key is never stored in the database. You can inspect the encryption code at [`backend/app/core/security.py`](https://github.com/dettinjo/routepass/blob/main/backend/app/core/security.py).

## Polling

Because Komoot has no webhooks, RoutePass polls your tour list periodically.

| Tier | Poll interval |
|------|--------------|
| Free | ~2 hours |
| Pro | ~10 minutes |

Polls are staggered across users to reduce IP-based rate limit risk. Each poll fetches only tours newer than your last sync timestamp.

## Initial history sync

On first connect, RoutePass backfills your recent history:

| Tier | History depth |
|------|--------------|
| Free | Last 30 days |
| Pro | Last 12 months |

## Sport type mapping

RoutePass maps all 44 Komoot sport types to the correct Strava `sport_type`. A few notable mappings:

| Komoot | Strava |
|--------|--------|
| `touringbicycle` | `Ride` |
| `mtb` | `MountainBikeRide` |
| `hike` | `Hike` |
| `jogging` | `Run` |
| `nordic_walking` | `NordicSki` |
| `e_mtb` | `EMountainBikeRide` |

## Limitations and risks

**Unofficial API** — Komoot's API (`api/v007`) is reverse-engineered. It has no public documentation and Komoot has changed it before. RoutePass monitors for errors and updates the client promptly, but brief outages are possible.

**IP-block risk at scale** — At large user counts, many polls originating from the same server IP may trigger Komoot rate limiting. We mitigate this by staggering polls with jitter and using multiple egress IPs. Self-hosters have zero risk — each user's polls come from their own IP.

**Terms of Service** — Unofficial API use technically violates Komoot's ToS. We disclose this openly. At typical indie-SaaS scale, enforcement is unlikely.

## Disconnecting

Go to **Connections → Komoot → Disconnect**. Your encrypted credentials are permanently deleted from our database.

---
title: Sync Rules Overview
description: How the RoutePass rule engine works — conditions, actions, and evaluation order.
---

Sync rules let you control exactly which activities get synced and how they are transformed in transit.

## How rules work

Each rule has two parts:

- **Conditions** — criteria that must match for the rule to fire
- **Actions** — what happens when the rule fires

Rules are evaluated in **order** (lowest `rule_order` first). The first rule whose conditions all match is applied and evaluation **stops** — subsequent rules are not checked. This is called "first-match" or "stop" semantics.

```
Rule 1: sport_type is [yoga] → skip
Rule 2: distance_km lt 5     → skip
Rule 3: (no conditions)      → append_description "📍 Komoot"
```

In this example:
- A yoga session → skipped by Rule 1 (never reaches Rule 2 or 3)
- A 3 km run → skipped by Rule 2 (not yoga, so Rule 1 didn't match)
- A 20 km ride → gets the description appended by Rule 3

## Tier limits

| Tier | Rules per pipeline |
|------|--------------------|
| Free | 1 |
| Pro | 5 |
| Self-hosted | Unlimited |

## Common presets

The dashboard offers one-click presets for the most common use cases:

| Preset | Conditions | Action |
|--------|-----------|--------|
| Skip indoor activities | `sport_type is [yoga, indoor_cycling, fitness]` | `skip` |
| Only sync rides >10 km | `sport_type is [*cycling*]` + `distance_km lt 10` | `skip` |
| Add Komoot attribution | (none — catch-all) | `append_description "📍 Komoot tour"` |
| Fix hiking sport type | `sport_type is [hike]` | `set_sport_type Hike` |

## Rule scope

Rules are scoped to a **pipeline** (source → destination pair). A rule on your Komoot → Strava pipeline does not affect your Komoot → Intervals.icu pipeline.

## Reference pages

- [Conditions](/sync-rules/conditions/) — full list of condition types and operators
- [Actions](/sync-rules/actions/) — full list of action types and parameters

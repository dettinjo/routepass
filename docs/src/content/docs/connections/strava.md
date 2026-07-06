---
title: Strava
description: Connecting Strava as a source and destination platform in RoutePass.
---

Strava is a **bidirectional** platform in RoutePass — it can act as both a **source** (activities you record on Strava flow into RoutePass) and a **destination** (activities from other sources are uploaded to your Strava feed).

## Connecting

1. Go to **Connections → Connect Strava**.
2. You'll be redirected to Strava's OAuth consent page.
3. Click **Authorize**.
4. You'll be redirected back to RoutePass. The connection is now active.

## OAuth scopes

RoutePass requests only two scopes:

| Scope | Why |
|-------|-----|
| `activity:read_all` | Ingest your Strava activities into the RoutePass hub |
| `activity:write` | Upload activities from other sources and update metadata |

We do not request access to your profile, segments, clubs, or gear.

## How tokens are stored

Your Strava access token and refresh token are encrypted with AES-256 (Fernet) before being written to the database. Tokens are automatically refreshed when they expire (Strava tokens expire every 6 hours).

## Strava as a source

When Strava is connected, RoutePass ingests your activities in two ways:

**Real-time (webhook):** Strava sends a push notification to RoutePass whenever you record or upload an activity. RoutePass processes it immediately and adds it to the activity hub.

**Backfill poll:** On connection and every subsequent sync, RoutePass fetches any activities created since the last sync watermark (up to 90 days back on first connect). This catches activities recorded while RoutePass was offline or before you connected.

Both paths are idempotent — an activity already in the hub is never duplicated.

## Strava as a destination

Activities sourced from Komoot (or imported via GPX) can be pushed to Strava as GPX uploads. Each upload goes through the `sync_gpx_to_strava` background job.

RoutePass sets `external_id=komoot_{tour_id}` on every Strava upload. Strava automatically rejects a second upload with the same `external_id`, so even if RoutePass syncs the same activity twice (e.g. after a reconnect), only one activity appears in your feed.

## Map display for Strava activities

When you open a Strava-sourced activity in the RoutePass dashboard, the map is rendered by fetching the activity's GPS streams directly from the Strava API (`latlng`, `altitude`, `time`). These are converted to a standard GPX track on the fly — nothing is stored permanently. Activities without GPS data (e.g. indoor rides, treadmill runs) will not show a map.

## `hide_from_home`

By default, RoutePass sets `hide_from_home=true` on all activities uploaded **to** Strava. This keeps your feed clean — activities are visible on your profile but won't appear in followers' feeds.

You can override this per-rule using the `set_hide_from_home` action in your sync rules.

:::note
Strava's API no longer supports setting `visibility=only_me` programmatically. `hide_from_home=true` is the closest equivalent available via API.
:::

## Rate limits

Strava enforces **1,000 requests per day** and **100 requests per 15 minutes** per registered application, shared across all users of that app.

Ingesting Strava activities (source path) costs 1–2 API calls per page of 50 activities. Uploading to Strava (destination path) costs approximately 4–5 API calls per activity (upload, poll until ready, update metadata).

RoutePass manages this with a priority queue:
- **Pro users** are always served first
- **Free tier** syncs are suspended when the daily budget exceeds 800 requests (150 reserved for Pro)

See [Rate Limits](/api/rate-limits/) for full details.

## Webhook

RoutePass registers one Strava webhook subscription per Strava API app. When any authorized athlete records or uploads an activity on Strava, Strava pushes a notification to RoutePass at `POST /api/v1/webhooks/strava`. This triggers immediate ingestion into the activity hub.

## Disconnecting

Go to **Connections → Strava → Disconnect**. Your encrypted tokens are permanently deleted. Strava is not notified — if you want to fully revoke access, also visit your [Strava Connected Apps](https://www.strava.com/settings/apps) and revoke RoutePass there.

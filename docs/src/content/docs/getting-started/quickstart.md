---
title: Quickstart
description: Connect your first source and destination in under five minutes.
---

This guide walks you from a blank account to your first automatically synced activity.

## Prerequisites

- A [RoutePass account](https://routepass.online/register) (free)
- At least one of: a Komoot account with recorded activities, or a Strava account
- A destination to sync to (Strava, Intervals.icu, or Runalyze)

## Step 1 — Register

Go to [routepass.online/register](https://routepass.online/register) and create an account with your email and password. You can also sign in with Google or GitHub. You'll be logged in immediately.

## Step 2 — Connect your sources

Navigate to **Connections** in the sidebar.

**Komoot:**
1. Under **Sources**, click **Connect Komoot**.
2. Enter your Komoot email and password. These are encrypted with AES-256 before storage and are only used to poll your tour list.
3. Click **Save**. RoutePass immediately queues a backfill of your last 30 days of tours (Free) or 12 months (Pro).

:::note
Komoot doesn't offer OAuth — they use Basic Auth for their unofficial API. See [Komoot connection details](/connections/komoot/) for more on how we handle this securely.
:::

**Strava (as a source):**
1. Click **Connect Strava**.
2. You'll be redirected to Strava's OAuth consent screen.
3. Click **Authorize** — RoutePass requests `activity:read_all` and `activity:write`.
4. You'll be redirected back. RoutePass immediately backfills your last 90 days of Strava activities. Going forward, new Strava activities arrive via real-time webhook within seconds.

## Step 3 — Connect a destination

Still in **Connections**, connect at least one destination:

- **Strava** — if you connected Strava as a source above, it is also available as a destination. Activities from Komoot or GPX imports can be pushed to your Strava feed.
- **Intervals.icu** — paste your API key and athlete ID from your Intervals.icu settings.
- **Runalyze** — paste your personal access token (requires Runalyze Supporter tier).

## Step 4 — Verify your first sync

1. Go to **Activities**. The page automatically triggers a background sync on load — you'll see a **Refresh** button in the top-right of the card that spins while syncing.
2. Your activities should appear within a few seconds (or up to 5 seconds after the background sync completes).
3. Each activity shows which platforms it's present on. An activity on both Komoot and Strava shows both platform badges.

:::tip
On the Free tier, new activities sync in batches roughly every 2 hours. Upgrade to Pro for near-realtime sync (~10 minutes) and a longer activity history (12 months vs 30 days).
:::

## Step 5 — View an activity

Click any activity to open the detail view. Activities with GPS tracks show a live map:

- **Komoot activities** — GPS track fetched directly from the Komoot API.
- **Strava activities** — GPS streams fetched from the Strava API and converted to a route on the fly.
- **GPX imports** — GPS track stored locally from the uploaded file.

## Step 6 — (Optional) Add a sync rule

1. Go to **Rules** in the sidebar.
2. Click **New rule**.
3. Example: skip all yoga sessions — set condition `sport_type is [yoga]`, action `skip`.
4. Save. The rule applies to all future syncs on matching pipelines.

## What's next

- [Configure more connections](/connections/overview/) — add Intervals.icu or Runalyze as additional destinations
- [Learn sync rules](/sync-rules/overview/) — filter, transform, and control exactly what gets synced
- [Explore the API](/api/authentication/) — automate with API keys

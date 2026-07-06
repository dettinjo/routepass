---
title: Intervals.icu
description: Connecting Intervals.icu as a destination platform in RoutePass.
---

[Intervals.icu](https://intervals.icu) is a free training analysis platform popular among cyclists and triathletes. RoutePass can push activities to Intervals.icu as a Pro destination.

## Prerequisites

- An Intervals.icu account (free)
- Your **athlete ID** (visible in your Intervals.icu profile URL: `intervals.icu/athlete/i12345`)
- An **API key** from Intervals.icu settings

## Getting your API key

1. Log into Intervals.icu.
2. Go to **Settings → API** (or your profile icon → API key).
3. Copy the key — it starts with `intervals_`.

## Connecting

1. In RoutePass, go to **Connections → Destinations → Connect Intervals.icu**.
2. Enter your **athlete ID** (just the number, e.g. `12345`).
3. Enter your **API key**.
4. Click **Save**.

RoutePass verifies the credentials immediately by making a test request.

## What gets pushed

For each synced activity, RoutePass pushes:

- Activity name
- Sport type (mapped from Komoot → Strava → Intervals.icu format)
- Start time
- Distance
- Elevation gain
- Duration
- GPX track (if available from Komoot)

RoutePass does **not** push heart rate, power, or sensor data — that data is not available in Komoot GPX exports.

## Rate limits

Intervals.icu allows approximately 1 request per second with no published daily cap. RoutePass respects this limit and will not burst beyond it.

## Disconnecting

Go to **Connections → Intervals.icu → Disconnect**. Your API key is permanently deleted.

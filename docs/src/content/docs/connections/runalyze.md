---
title: Runalyze
description: Connecting Runalyze as a destination platform in RoutePass.
---

[Runalyze](https://runalyze.com) is a German training analysis platform with detailed physiological metrics. RoutePass pushes activities to Runalyze via GPX upload as a Pro destination.

## Prerequisites

- A Runalyze account with **Supporter tier** (€1–2/month — required to access the API)
- A personal access token from Runalyze settings

## Getting your access token

1. Log into Runalyze.
2. Go to **My Account → API**.
3. Generate a personal access token and copy it.

## Connecting

1. In RoutePass, go to **Connections → Destinations → Connect Runalyze**.
2. Enter your **personal access token**.
3. Click **Save**.

## What gets pushed

Runalyze accepts raw GPX uploads. RoutePass sends the original GPX file downloaded from Komoot, which includes:

- GPS track (coordinates + elevation)
- Timestamps
- Activity name and description (as GPX metadata)

Runalyze parses the GPX and derives its own analytics (pace, elevation profiles, training load, VDOT, etc.).

## Rate limits

Runalyze allows **30 requests per minute** per token. RoutePass queues uploads and will not exceed this limit. For users with a large initial backfill, this means uploads are spaced out over several minutes.

## Disconnecting

Go to **Connections → Runalyze → Disconnect**. Your access token is permanently deleted.

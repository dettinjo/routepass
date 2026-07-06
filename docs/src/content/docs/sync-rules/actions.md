---
title: Actions
description: Full reference for all action types in RoutePass sync rules.
---

Actions define what happens when a rule's conditions match. Each rule has exactly one action.

## `skip`

Do not sync this activity. It is recorded in the sync history with status `skipped` but never pushed to any destination.

```json
{ "type": "skip" }
```

**Common use cases:**
- Skip indoor sessions
- Skip test recordings
- Skip activities below a distance threshold

---

## `set_sport_type`

Override the Strava `sport_type` value before uploading. Useful when Komoot's classification doesn't match what you want on Strava.

```json
{
  "type": "set_sport_type",
  "value": "GravelRide"
}
```

**Supported Strava sport types** (selection):

`Run`, `Trail Run`, `Walk`, `Hike`,
`Ride`, `MountainBikeRide`, `GravelRide`, `EBikeRide`, `EMountainBikeRide`,
`VirtualRide`, `Swim`, `NordicSki`, `AlpineSki`,
`Kayaking`, `Rowing`, `StandUpPaddling`, `Surfing`,
`WeightTraining`, `Yoga`, `Workout`, `Other`

Full list: [Strava API sport type reference](https://developers.strava.com/docs/reference/#api-models-SportType)

---

## `name_template`

Override the activity name using a template string. Supports the following placeholders:

| Placeholder | Description |
|-------------|-------------|
| `{name}` | Original Komoot tour name |
| `{distance:.0f}` | Distance in km, rounded to 0 decimal places |
| `{distance:.1f}` | Distance in km, 1 decimal place |
| `{elevation}` | Elevation gain in metres |
| `{duration}` | Duration in `HH:MM` format |
| `{sport}` | Sport type |

**Example — add distance and elevation to every name:**
```json
{
  "type": "name_template",
  "value": "{name} · {distance:.0f}km · {elevation}m↑"
}
```

Result: `Alpine Loop · 48km · 1240m↑`

---

## `append_description`

Append text to the end of the activity description. The original Komoot description is preserved; the appended text follows on a new line.

```json
{
  "type": "append_description",
  "value": "📍 Komoot tour — routepass.online"
}
```

**Common use cases:**
- Add attribution text
- Add hashtags (`#komoot #cycling`)
- Add links

---

## `set_hide_from_home`

Override the `hide_from_home` flag for this activity. By default, RoutePass sets `hide_from_home=true` on all synced activities.

```json
{
  "type": "set_hide_from_home",
  "value": false
}
```

Set to `false` to make specific activities appear in your followers' Strava feed (e.g. race results or personal bests you want to share).

:::note
Strava's API does not support setting `visibility=only_me`. `hide_from_home` is the only visibility control available via the upload API.
:::

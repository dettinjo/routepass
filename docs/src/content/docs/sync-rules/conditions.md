---
title: Conditions
description: Full reference for all condition types in RoutePass sync rules.
---

Conditions define when a rule fires. All conditions in a rule must match for the rule to apply (logical AND). If a rule has no conditions, it always matches (catch-all).

## `sport_type`

Match by the Komoot sport type of the activity.

| Operator | Description |
|----------|-------------|
| `is` | Sport type is one of the listed values |
| `is_not` | Sport type is not any of the listed values |

**Example — skip yoga and indoor cycling:**
```json
{
  "field": "sport_type",
  "op": "is",
  "value": ["yoga", "indoor_cycling", "fitness"]
}
```

**Supported Komoot sport types** (44 total):

`road_cycling`, `mtb`, `mountainbike`, `touringbicycle`, `e_mtb`, `e_road`, `e_touringbicycle`,
`hike`, `jogging`, `running`, `trail_running`, `walking`, `nordic_walking`,
`climbing`, `skitour`, `snowshoeing`, `cross_country_skiing`, `downhill_skiing`,
`skiing`, `snowboarding`, `kayaking`, `canoeing`, `rowing`, `stand_up_paddling`,
`surfing`, `windsurfing`, `kitesurfing`, `swimming`, `open_water_swimming`,
`triathlon`, `cycling`, `gravel_cycling`, `fixie`, `bike_touring`,
`yoga`, `fitness`, `indoor_cycling`, `gym`, `skateboarding`, `horse_riding`,
`golf`, `volleyball`, `tennis`, `other`

---

## `distance_km`

Match by the total distance of the activity in kilometres.

| Operator | Description |
|----------|-------------|
| `gt` | Distance greater than value |
| `lt` | Distance less than value |
| `between` | Distance between two values (inclusive) |

**Example — skip activities shorter than 5 km:**
```json
{
  "field": "distance_km",
  "op": "lt",
  "value": 5
}
```

**Example — match activities between 10 and 50 km:**
```json
{
  "field": "distance_km",
  "op": "between",
  "value": [10, 50]
}
```

---

## `elevation_m`

Match by total elevation gain in metres.

| Operator | Description |
|----------|-------------|
| `gt` | Elevation greater than value |
| `lt` | Elevation less than value |

**Example — flag big climbing days:**
```json
{
  "field": "elevation_m",
  "op": "gt",
  "value": 2000
}
```

---

## `duration_min`

Match by total activity duration in minutes.

| Operator | Description |
|----------|-------------|
| `gt` | Duration greater than value |
| `lt` | Duration less than value |

**Example — skip activities under 10 minutes (likely test recordings):**
```json
{
  "field": "duration_min",
  "op": "lt",
  "value": 10
}
```

---

## `name_contains`

Match by a substring of the activity name (case-insensitive).

**Example — skip activities named with "test":**
```json
{
  "field": "name_contains",
  "op": "contains",
  "value": "test"
}
```

This condition is useful for skipping ad-hoc recordings or routing specific activities to different destinations.

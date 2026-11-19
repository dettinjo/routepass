"""Sync rules: conditions decide whether an activity is copied, actions shape the copy.

Rules for one direction are evaluated by ascending priority; the first enabled rule
whose conditions all match decides. When none matches, the direction's default action
(sync / skip) applies.

conditions (all optional, AND-combined):
  sports / exclude_sports   list of canonical (Strava) sport types
  families                  list of ride | run | walk | winter | water | other
  distance_km, elevation_m, duration_min   {"min": x, "max": y}
  name_contains             case-insensitive substring
  name_regex                Python regular expression (search)
  weekdays                  list of 0=Mon … 6=Sun
  date                      {"from": "YYYY-MM-DD", "to": "YYYY-MM-DD"}
  commute, trainer, has_heartrate, has_power   booleans (Strava data)
  start_near, end_near      {"place": "Home"} (a saved place) or {"lat", "lng"}, optional "radius_km" (default 1)

actions:
  skip                      true → never sync matching activities
  name                      template, e.g. "{name} · {distance_km:.0f} km"
  description               template replacing the description
  append_description        text appended to the description
  sport                     target-platform sport (Strava sport_type or Komoot sport key)
  strava                    {"hide_from_home": bool, "commute": bool, "trainer": bool, "gear_id": str}
  komoot                    {"visibility": "private" | "friends" | "public"}

Template fields: name, sport, sport_label, distance_km, elevation_m, duration_min,
moving_time, date, time, weekday, source.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from routepass.models import Activity, SyncRule
from routepass.providers import sports

DIRECTION_TARGET = {"strava_to_komoot": "komoot", "komoot_to_strava": "strava"}
DIRECTION_SOURCE = {"strava_to_komoot": "strava", "komoot_to_strava": "komoot"}
CONDITION_KEYS = {
    "sports",
    "exclude_sports",
    "families",
    "distance_km",
    "elevation_m",
    "duration_min",
    "name_contains",
    "name_regex",
    "weekdays",
    "date",
    "commute",
    "trainer",
    "has_heartrate",
    "has_power",
    "start_near",
    "end_near",
}
ACTION_KEYS = {"skip", "name", "description", "append_description", "sport", "strava", "komoot"}


class RuleError(ValueError):
    pass


def validate(direction: str, conditions: dict, actions: dict) -> None:
    if direction not in DIRECTION_TARGET:
        raise RuleError(f"direction must be one of {sorted(DIRECTION_TARGET)}")
    if unknown := set(conditions) - CONDITION_KEYS:
        raise RuleError(f"unknown condition(s): {sorted(unknown)}")
    if unknown := set(actions) - ACTION_KEYS:
        raise RuleError(f"unknown action(s): {sorted(unknown)}")
    if rx := conditions.get("name_regex"):
        try:
            re.compile(rx)
        except re.error as exc:
            raise RuleError(f"invalid name_regex: {exc}") from exc
    for key in ("distance_km", "elevation_m", "duration_min"):
        rng = conditions.get(key)
        if rng is not None and (not isinstance(rng, dict) or set(rng) - {"min", "max"}):
            raise RuleError(f"{key} must be an object with min/max")
    for key in ("start_near", "end_near"):
        geo = conditions.get(key)
        if geo is None:
            continue
        if not isinstance(geo, dict) or not ({"lat", "lng"} <= set(geo) or "place" in geo):
            raise RuleError(f"{key} needs a saved place name or lat/lng (and optional radius_km)")
        try:
            for k in ("lat", "lng", "radius_km"):
                if geo.get(k) is not None:
                    float(geo[k])
        except (TypeError, ValueError) as exc:
            raise RuleError(f"{key} coordinates must be numbers") from exc
    vis = (actions.get("komoot") or {}).get("visibility")
    if vis is not None and vis not in ("private", "friends", "public"):
        raise RuleError("komoot.visibility must be private, friends or public")
    for key in ("name", "description"):
        if tmpl := actions.get(key):
            try:
                render(tmpl, _SAMPLE)
            except (KeyError, ValueError, IndexError) as exc:
                raise RuleError(f"invalid {key} template: {exc}") from exc


def _in_range(value: float | None, rng: dict | None) -> bool:
    if not rng:
        return True
    if value is None:
        return False
    if rng.get("min") is not None and value < rng["min"]:
        return False
    if rng.get("max") is not None and value > rng["max"]:
        return False
    return True


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (
        math.sin((p2 - p1) / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    )
    return 2 * 6371.0 * math.asin(min(1.0, math.sqrt(a)))


def _near(lat: float | None, lng: float | None, geo: dict | None, places: list[dict] | None) -> bool:
    if not geo:
        return True
    if "place" in geo:
        place = next(
            (p for p in places or [] if p.get("name", "").lower() == str(geo["place"]).lower()), None
        )
        if place is None:
            return False  # unknown place never matches (safer than matching everything)
        geo = {**place, **{k: v for k, v in geo.items() if k == "radius_km"}}
    if lat is None or lng is None:
        return False
    radius = float(geo.get("radius_km") or 1.0)
    return _haversine_km(lat, lng, float(geo["lat"]), float(geo["lng"])) <= radius


def matches(conditions: dict, act: Activity, places: list[dict] | None = None) -> bool:
    c = conditions
    if not _near(act.start_lat, act.start_lng, c.get("start_near"), places):
        return False
    if not _near(act.end_lat, act.end_lng, c.get("end_near"), places):
        return False
    if c.get("sports") and act.sport not in c["sports"]:
        return False
    if c.get("exclude_sports") and act.sport in c["exclude_sports"]:
        return False
    if c.get("families") and act.family not in c["families"]:
        return False
    if not _in_range((act.distance_m or 0) / 1000, c.get("distance_km")):
        return False
    if not _in_range(act.elevation_gain_m or 0, c.get("elevation_m")):
        return False
    if not _in_range((act.moving_time_s or 0) / 60, c.get("duration_min")):
        return False
    if c.get("name_contains") and c["name_contains"].lower() not in (act.name or "").lower():
        return False
    if c.get("name_regex") and not re.search(c["name_regex"], act.name or "", re.IGNORECASE):
        return False
    local = act.start_local or act.start_time
    if c.get("weekdays") and local.weekday() not in c["weekdays"]:
        return False
    if rng := c.get("date"):
        d = local.date()
        if rng.get("from") and d < date.fromisoformat(rng["from"]):
            return False
        if rng.get("to") and d > date.fromisoformat(rng["to"]):
            return False
    for flag in ("commute", "trainer"):
        if c.get(flag) is not None and bool(getattr(act, flag)) != bool(c[flag]):
            return False
    if c.get("has_heartrate") is not None and (act.avg_hr is not None) != bool(c["has_heartrate"]):
        return False
    if c.get("has_power") is not None and (act.avg_power is not None) != bool(c["has_power"]):
        return False
    return True


class _Fields(dict):
    def __missing__(self, key: str) -> str:
        raise KeyError(key)


_SAMPLE = _Fields(
    name="Morning Ride",
    sport="Ride",
    sport_label="Ride",
    distance_km=42.2,
    elevation_m=512,
    duration_min=95,
    moving_time="1:35",
    date="2026-01-01",
    time="08:00",
    weekday="Thursday",
    source="komoot",
)


def template_fields(act: Activity, source: str) -> _Fields:
    local = act.start_local or act.start_time
    minutes = int((act.moving_time_s or 0) // 60)
    return _Fields(
        name=act.name or "",
        sport=act.sport,
        sport_label=sports.label(act.sport),
        distance_km=round((act.distance_m or 0) / 1000, 2),
        elevation_m=int(act.elevation_gain_m or 0),
        duration_min=minutes,
        moving_time=f"{minutes // 60}:{minutes % 60:02d}",
        date=local.strftime("%Y-%m-%d"),
        time=local.strftime("%H:%M"),
        weekday=local.strftime("%A"),
        source=source,
    )


def render(template: str, fields: dict) -> str:
    return template.format_map(fields)


@dataclass
class Decision:
    sync: bool
    rule_id: int | None
    reason: str
    plan: dict[str, Any] = field(default_factory=dict)


def _merge_actions(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = {**out[k], **v}
        else:
            out[k] = v
    return out


def decide(
    act: Activity,
    direction: str,
    rules: list[SyncRule],
    direction_prefs: dict,
    description: str = "",
    places: list[dict] | None = None,
) -> Decision:
    """Pick the rule for this activity and build the upload plan."""
    rule = next(
        (
            r
            for r in sorted(rules, key=lambda r: (r.priority, r.id or 0))
            if r.enabled and r.direction == direction and matches(r.conditions or {}, act, places)
        ),
        None,
    )
    defaults = direction_prefs.get("defaults") or {}
    if rule is None:
        if direction_prefs.get("default_action", "sync") == "skip":
            return Decision(False, None, "no rule matched (default: skip)")
        actions = defaults
        reason = "no rule matched (default: sync)"
    else:
        if (rule.actions or {}).get("skip"):
            return Decision(False, rule.id, f"rule “{rule.name}” skips it")
        actions = _merge_actions(defaults, rule.actions or {})
        reason = f"rule “{rule.name}”"

    target = DIRECTION_TARGET[direction]
    fields = template_fields(act, DIRECTION_SOURCE[direction])
    name = act.name or sports.label(act.sport)
    if actions.get("name"):
        try:
            name = render(actions["name"], fields)
        except (KeyError, ValueError, IndexError):
            pass
    desc = description
    if actions.get("description"):
        try:
            desc = render(actions["description"], fields)
        except (KeyError, ValueError, IndexError):
            pass
    if actions.get("append_description"):
        desc = f"{desc}\n\n{actions['append_description']}".strip()

    if target == "strava":
        sport = actions.get("sport") or act.sport
    else:
        sport = actions.get("sport") or sports.strava_to_komoot(act.sport)
    plan: dict[str, Any] = {"name": name[:250], "description": desc, "sport": sport}
    if target == "strava" and actions.get("strava"):
        plan["strava"] = dict(actions["strava"])
    if target == "komoot":
        plan["komoot"] = {"visibility": "private", **(actions.get("komoot") or {})}
    # The copy gets the original's visibility, unless the rule itself sets one.
    from routepass.engine import visibility as vis

    rule_actions = (rule.actions or {}) if rule else {}
    src = next((s for s in act.sources if s.provider == DIRECTION_SOURCE[direction] and not s.deleted), None)
    level = vis.level_of(src) if direction_prefs.get("match_visibility", True) else None
    if level and target == "komoot" and not (rule_actions.get("komoot") or {}).get("visibility"):
        plan["komoot"]["visibility"] = level
    if level and target == "strava" and not (rule_actions.get("strava") or {}).get("visibility"):
        plan["strava"] = {**(plan.get("strava") or {}), "visibility": vis.to_strava(level)}
    return Decision(True, rule.id if rule else None, reason, plan)

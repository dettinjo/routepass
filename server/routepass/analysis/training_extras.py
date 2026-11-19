"""Day-to-day training plan helpers: personal zones, "why this session", compliance levels, effort
feedback (session RPE → training load) and quick session variants (shorter / easier / swap).

Kept separate from analysis/training.py, which builds and adapts whole plans.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from routepass.analysis.track import HR_ZONE_FRACTIONS, POWER_ZONE_FRACTIONS
from routepass.models import Activity, TrainingSession, TrainingWeek

# ── personal zones ───────────────────────────────────────────────────────────

# Flat running pace per zone as a multiple of your easy (Z2) pace; > 1 = slower.
_PACE_FACTORS = {1: (1.12, 1.25), 2: (0.97, 1.08), 3: (0.88, 0.95), 4: (0.81, 0.87), 5: (0.72, 0.80)}


def personal_zones(profile: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    """Heart-rate, flat-pace and power ranges for zones 1–5 from the profile and recent training.

    Pace is anchored on the median grade-adjusted pace of recent runs, which for most athletes is an
    easy aerobic (Z2) effort; it is an estimate and labelled as such."""
    out: dict[str, Any] = {"hr": None, "pace": None, "power": None, "notes": []}
    hr_max = profile.get("hr_max")
    if hr_max:
        b = [0.5, *HR_ZONE_FRACTIONS, 1.0]
        out["hr"] = {str(z): [round(b[z - 1] * hr_max), round(b[z] * hr_max)] for z in range(1, 6)}
    else:
        out["notes"].append("Add your max heart rate to see heart-rate targets.")
    gap = baseline.get("median_gap_ms")
    if gap:
        easy_s_per_km = 1000.0 / float(gap)
        out["pace"] = {
            str(z): [round(easy_s_per_km * lo), round(easy_s_per_km * hi)]
            for z, (lo, hi) in _PACE_FACTORS.items()
        }
        out["notes"].append("Pace on flat ground, estimated from your recent runs.")
    ftp = profile.get("ftp") or baseline.get("ftp_w")
    if ftp:
        b = [0.0, *POWER_ZONE_FRACTIONS]
        out["power"] = {str(z): [round(b[z - 1] * ftp), round(b[z] * ftp)] for z in range(1, 6)}
    return out


# Which zone a session type is mostly ridden or run in.
SESSION_ZONE = {
    "recovery": "1",
    "easy": "2",
    "long": "2",
    "brick": "2",
    "tempo": "3",
    "hills": "4",
    "intervals": "4",
    "race": "3",
    "strides": "2",
}


# ── why this session ─────────────────────────────────────────────────────────

_PURPOSE = {
    "easy": "Builds your aerobic base at a cost you recover from overnight.",
    "long": "Endurance: teaches your body to keep going and to fuel on the move.",
    "tempo": "Raises the pace you can hold for a long time.",
    "intervals": "Short hard efforts that lift your top-end fitness (VO2max).",
    "hills": "Climbing strength and running economy on gradients.",
    "recovery": "Gentle movement so the hard days can sink in.",
    "brick": "Practises running on tired legs straight after the bike.",
    "race": "Race day — trust the work you have done.",
    "strength": "Strength and mobility that keep you robust.",
}
_PHASE_WORDS = {
    "base": "Base phase",
    "build": "Build phase",
    "peak": "Peak phase",
    "taper": "Taper",
    "race_week": "Race week",
    "recovery": "Recovery week",
}


def session_why(s: TrainingSession, week: TrainingWeek | None, prev_week: TrainingWeek | None) -> str:
    purpose = _PURPOSE.get(s.session_type) or _PURPOSE.get(s.sport) or "Part of this week's plan."
    parts = [purpose]
    if s.priority == "key":
        parts.append("A key session — protect it when the week gets busy.")
    if week is not None:
        phase = _PHASE_WORDS.get(week.phase, week.phase)
        if prev_week is not None and prev_week.target_tss:
            change = (week.target_tss - prev_week.target_tss) / prev_week.target_tss * 100
            trend = "same load as last week" if abs(change) < 3 else f"load {change:+.0f}% on last week"
            parts.append(f"{phase}, week {week.week_index}: {trend}.")
        else:
            parts.append(f"{phase}, week {week.week_index}.")
    return " ".join(parts)


# ── compliance ───────────────────────────────────────────────────────────────


def compliance_level(s: TrainingSession, today: date) -> str:
    """on | partial | off | missed | skipped | planned — the TrainingPeaks-style colour of a session."""
    if s.status == "skipped":
        return "skipped"
    if s.matched_activity_id is not None or s.status in ("completed", "partial"):
        score = s.compliance_score if s.compliance_score is not None else 100.0
        return "on" if score >= 80 else "partial" if score >= 50 else "off"
    if s.status == "missed" or (s.sport != "rest" and date.fromisoformat(s.scheduled_date) < today):
        return "missed"
    return "planned"


# ── effort feedback ──────────────────────────────────────────────────────────

# Session RPE (1–10) → intensity factor, so load = hours × IF² × 100 stays on the TSS scale.
_RPE_IF = {1: 0.50, 2: 0.55, 3: 0.60, 4: 0.67, 5: 0.73, 6: 0.79, 7: 0.85, 8: 0.90, 9: 0.95, 10: 1.0}


def rpe_load(rpe: int | None, moving_s: float | None) -> float | None:
    if not rpe or not moving_s:
        return None
    factor = _RPE_IF[max(1, min(10, int(rpe)))]
    return round(moving_s / 3600.0 * factor**2 * 100, 1)


def apply_rpe(act: Activity) -> None:
    """Use the athlete's effort for load when neither power nor heart rate measured it."""
    if act.rpe and act.load_method in (None, "estimate", "rpe"):
        load = rpe_load(act.rpe, act.moving_time_s)
        if load is not None:
            act.load, act.load_method, act.intensity = load, "rpe", _RPE_IF[max(1, min(10, act.rpe))]


def rate_session(
    db: Session, s: TrainingSession, *, rpe: int | None, feel: str | None, note: str = ""
) -> dict[str, Any]:
    """Store how a session felt. The rating becomes the activity's load when nothing better exists,
    and two 'too hard' (or 'too easy') sessions in a row nudge the next sessions."""
    from routepass.engine import ingest

    s.rpe = rpe
    s.feel = feel
    s.feedback_note = (note or "").strip()[:300] or None
    if s.matched_activity_id:
        act = db.get(Activity, s.matched_activity_id)
        if act is not None:
            act.rpe = rpe
            if rpe:
                apply_rpe(act)
            elif act.load_method == "rpe":
                ingest.refresh_activity(db, act.id)  # rating removed: back to the measured/estimated load
    db.flush()

    adjusted: list[str] = []
    if feel in ("hard", "easy"):
        recent = list(
            db.scalars(
                select(TrainingSession)
                .where(
                    TrainingSession.plan_id == s.plan_id,
                    TrainingSession.feel.is_not(None),
                    TrainingSession.scheduled_date <= s.scheduled_date,
                    TrainingSession.scheduled_date
                    >= (date.fromisoformat(s.scheduled_date) - timedelta(days=10)).isoformat(),
                )
                .order_by(TrainingSession.scheduled_date.desc(), TrainingSession.id.desc())
                .limit(2)
            )
        )
        if len(recent) == 2 and all(r.feel == feel for r in recent):
            factor = 0.9 if feel == "hard" else 1.05
            upcoming = db.scalars(
                select(TrainingSession)
                .where(
                    TrainingSession.plan_id == s.plan_id,
                    TrainingSession.scheduled_date > s.scheduled_date,
                    TrainingSession.status.in_(("planned", "moved")),
                    TrainingSession.sport != "rest",
                )
                .order_by(TrainingSession.scheduled_date)
                .limit(2)
            ).all()
            for u in upcoming:
                if u.session_type == "race":
                    continue
                u.original_target = u.original_target or _snapshot(u)
                for attr in ("target_duration_s", "target_distance_km", "target_tss"):
                    setattr(u, attr, round(float(getattr(u, attr) or 0) * factor, 1))
                u.adaptation_note = (
                    "Eased by 10% after two sessions that felt too hard."
                    if feel == "hard"
                    else "Raised by 5% after two sessions that felt too easy."
                )
                u.status = "moved"
                adjusted.append(u.title)
            db.flush()
    return {"rpe": rpe, "feel": feel, "adjusted": adjusted}


# ── quick variants ───────────────────────────────────────────────────────────


def _snapshot(s: TrainingSession) -> dict[str, Any]:
    return {
        "scheduled_date": s.scheduled_date,
        "session_type": s.session_type,
        "title": s.title,
        "description": s.description,
        "workout_steps": list(s.workout_steps or []),
        "target_duration_s": s.target_duration_s,
        "target_distance_km": s.target_distance_km,
        "target_elev_m": s.target_elev_m,
        "target_tss": s.target_tss,
    }


def apply_variant(db: Session, s: TrainingSession, kind: str, minutes: int | None = None) -> dict[str, Any]:
    """shorter (to the time you have), easier (same time, easy effort), swap (with the next session)
    or original (undo). The plan's other sessions stay as they are."""
    if kind == "original":
        orig = s.original_target
        if not orig:
            raise ValueError("this session has not been changed")
        for key, value in orig.items():
            setattr(s, key, value)
        s.original_target = None
        s.adaptation_note = None
        s.status = "planned"
        db.flush()
        return {"session_id": s.id, "kind": kind}

    if s.status in ("completed", "partial", "skipped"):
        raise ValueError("only open sessions can be changed")
    s.original_target = s.original_target or _snapshot(s)

    if kind == "shorter":
        full = float(s.target_duration_s or 0) or 3600.0
        minutes = int(minutes or max(20, round(full / 60 * 0.6)))
        factor = max(0.2, min(1.0, minutes * 60 / full))
        s.target_duration_s = round(full * factor)
        s.target_distance_km = round(float(s.target_distance_km or 0) * factor, 1)
        s.target_elev_m = round(float(s.target_elev_m or 0) * factor)
        s.target_tss = round(float(s.target_tss or 0) * factor, 1)
        s.adaptation_note = f"Shortened to {minutes} min — keep the main part, trim warm-up and volume."
    elif kind == "easier":
        hours = float(s.target_duration_s or 0) / 3600.0
        s.session_type = "recovery" if s.session_type == "recovery" else "easy"
        s.target_tss = round(hours * 0.67**2 * 100, 1)
        s.target_distance_km = round(float(s.target_distance_km or 0) * 0.9, 1)
        s.workout_steps = [
            "Easy effort throughout (zone 1–2)",
            "Conversational — you could talk in full sentences",
        ]
        if not s.title.lower().startswith("easy"):
            s.title = f"Easy {s.title[0].lower()}{s.title[1:]}" if s.title else "Easy session"
        s.adaptation_note = "Made easier for today: same time, low effort."
    elif kind == "swap":
        nxt = db.scalars(
            select(TrainingSession)
            .where(
                TrainingSession.plan_id == s.plan_id,
                TrainingSession.scheduled_date > s.scheduled_date,
                TrainingSession.status.in_(("planned", "moved")),
                TrainingSession.sport != "rest",
            )
            .order_by(TrainingSession.scheduled_date, TrainingSession.id)
            .limit(1)
        ).first()
        if nxt is None or nxt.session_type == "race":
            new_date = (date.fromisoformat(s.scheduled_date) + timedelta(days=1)).isoformat()
            s.scheduled_date = new_date
            s.adaptation_note = "Moved to the next day."
        else:
            nxt.original_target = nxt.original_target or _snapshot(nxt)
            s.scheduled_date, nxt.scheduled_date = nxt.scheduled_date, s.scheduled_date
            s.week_id, nxt.week_id = nxt.week_id, s.week_id
            s.adaptation_note = f"Swapped with “{nxt.title}”."
            nxt.adaptation_note = f"Swapped with “{s.title}”."
            nxt.status = "moved"
    else:
        raise ValueError("kind must be shorter, easier, swap or original")
    s.status = "moved"
    db.flush()
    return {"session_id": s.id, "kind": kind}

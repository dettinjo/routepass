"""Google Calendar entries follow their plan: deleted with it, upcoming ones dropped on archive,
and leftovers of plans that are gone are removed by the next sync."""

from __future__ import annotations

import re
import time
from datetime import date, timedelta

import httpx
import respx
from sqlalchemy import select

from routepass import store
from routepass.analysis import training
from routepass.db import session_scope
from routepass.models import TrainingPlan, TrainingSession
from routepass.providers import gcal
from tests.conftest import AUTH

CAL = "cal1"
EVENTS = re.compile(rf"{re.escape(gcal.GCAL_API)}/calendars/{CAL}/events(/(?P<eid>[^?]+))?")


def _connect(db) -> None:
    store.set_secret(
        db, gcal._SECRET_KEY, {"refresh_token": "r", "access_token": "a", "expires_at": time.time() + 3600}
    )
    gcal.save_config(db, {"target_calendar_id": CAL})


def _plan_with_events(db, name: str) -> TrainingPlan:
    plan = training.create_plan(
        db,
        store.get_preferences(db),
        {"name": name, "plan_type": "trail_run", "event_date": "2027-07-08"},
        use_ai=False,
    )
    for s in plan.sessions:
        if s.sport != "rest":
            s.gcal_event_id = f"ev-{name}-{s.id}"
    db.flush()
    return plan


class FakeCalendar:
    """Holds events; answers list (with the privateExtendedProperty / q filters) and delete."""

    def __init__(self) -> None:
        self.events: dict[str, dict] = {}

    def add(self, eid: str, day: str, plan_id: int | None = None, legacy: bool = False) -> None:
        ev = {"id": eid, "start": {"dateTime": f"{day}T07:00:00+01:00"}, "description": "x"}
        if legacy:
            ev["description"] = "Plan: old\n\nOpen in RoutePass: http://x/training"
        else:
            ev["extendedProperties"] = {"private": {"routepass": "1", "plan_id": str(plan_id)}}
        self.events[eid] = ev

    def handler(self, request: httpx.Request, eid: str | None = None) -> httpx.Response:
        if request.method == "DELETE":
            return httpx.Response(204 if self.events.pop(eid, None) else 404)
        p = request.url.params
        items = list(self.events.values())
        if p.get("privateExtendedProperty"):
            items = [e for e in items if "extendedProperties" in e]
        if p.get("q"):
            items = [e for e in items if p["q"] in e["description"]]
        return httpx.Response(200, json={"items": items})


@respx.mock
def test_delete_plan_removes_all_its_calendar_events(client):
    cal = FakeCalendar()
    respx.route(url__regex=EVENTS.pattern).mock(side_effect=cal.handler)
    with session_scope() as db:
        _connect(db)
        plan = _plan_with_events(db, "a")
        pid = plan.id
        ids = [s.gcal_event_id for s in plan.sessions if s.gcal_event_id]
        for s in plan.sessions:
            if s.gcal_event_id:
                cal.add(s.gcal_event_id, s.scheduled_date, pid)
        cal.add("lost-track", "2026-01-01", pid)  # tagged, but no session points to it
        cal.add("someone-else", "2026-01-01", pid + 99)
    assert ids

    r = client.delete(f"/api/v1/training/plans/{pid}", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["calendar_events_removed"] == len(ids) + 1
    assert set(cal.events) == {"someone-else"}


@respx.mock
def test_archive_keeps_history_and_orphans_are_cleaned():
    cal = FakeCalendar()
    respx.route(url__regex=EVENTS.pattern).mock(side_effect=cal.handler)
    today = date.today()
    with session_scope() as db:
        _connect(db)
        plan = _plan_with_events(db, "b")
        sessions = [s for s in plan.sessions if s.gcal_event_id]
        sessions[0].scheduled_date = (today - timedelta(days=3)).isoformat()  # a past one
        for s in sessions:
            cal.add(s.gcal_event_id, s.scheduled_date, plan.id)
        past_id = sessions[0].gcal_event_id
        n = training.remove_calendar_events(db, plan, upcoming_only=True)
        assert n == len(sessions) - 1 and set(cal.events) == {past_id}
        assert (
            db.scalar(select(TrainingSession.gcal_event_id).where(TrainingSession.id == sessions[0].id))
            == past_id
        )

        cal.add("from-a-deleted-plan", today.isoformat(), 12345)
        cal.add("legacy-untagged", today.isoformat(), legacy=True)
        assert gcal.cleanup_orphan_events(db) == 2
        assert set(cal.events) == {past_id}  # still referenced by the archived plan


def test_nothing_happens_without_a_connected_calendar():
    with session_scope() as db:
        plan = _plan_with_events(db, "c")
        assert training.remove_calendar_events(db, plan, upcoming_only=False) == 0
        assert gcal.cleanup_orphan_events(db) == 0

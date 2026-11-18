from __future__ import annotations

import re
from datetime import timedelta

import httpx
from sqlalchemy import func, select

from routepass import store
from routepass.db import session_scope
from routepass.engine import runner
from routepass.models import Activity, ProviderActivity, SyncJob
from routepass.timeutil import utcnow
from tests.conftest import AUTH, T0, coords, days, komoot_tour, strava_activity, streams

STRAVA = "https://www.strava.com/api/v3"
KOMOOT = "https://www.komoot.de/api/v007"


def _komoot_list(router, tours):
    router.get(f"{KOMOOT}/users/42/tours/").mock(
        return_value=httpx.Response(200, json={"_embedded": {"tours": tours}, "page": {"totalPages": 1}})
    )


def _strava_list(router, acts):
    router.get(f"{STRAVA}/athlete/activities").mock(return_value=httpx.Response(200, json=acts))


def _age_records():
    with session_scope() as db:
        for rec in db.scalars(select(ProviderActivity)):
            rec.first_seen = utcnow() - timedelta(hours=1)


def test_dedup_merges_same_activity_from_both_platforms(connected, mock_apis):
    _strava_list(mock_apis, [strava_activity(1, T0), strava_activity(2, T0 + days(1), km=10)])
    _komoot_list(
        mock_apis,
        [komoot_tour(100, T0 + timedelta(minutes=2), km=30.8), komoot_tour(101, T0 + days(3), km=50)],
    )
    mock_apis.get(re.compile(rf"{STRAVA}/activities/\d+/streams")).mock(
        return_value=httpx.Response(200, json=streams())
    )
    mock_apis.get(re.compile(rf"{KOMOOT}/tours/\d+/coordinates")).mock(
        return_value=httpx.Response(200, json=coords())
    )

    result = runner.run_cycle("test", tracks=True)
    assert result["status"] == "ok", result

    with session_scope() as db:
        assert db.scalar(select(func.count()).select_from(Activity)) == 3
        assert db.scalar(select(func.count()).select_from(ProviderActivity)) == 4
        merged = db.scalar(select(Activity).where(Activity.name == "Strava 1"))
        assert {s.provider for s in merged.sources} == {"strava", "komoot"}
        assert merged.has_track and merged.track_provider == "strava"


def test_komoot_to_strava_sync_never_duplicates(connected, mock_apis):
    _strava_list(mock_apis, [])
    _komoot_list(mock_apis, [komoot_tour(100, T0)])
    with session_scope() as db:
        store.update_preferences(db, {"sync": {"komoot_to_strava": {"enabled": True}}})
    runner.run_cycle("test", tracks=False)
    _age_records()

    mock_apis.get(f"{KOMOOT}/tours/100.gpx").mock(return_value=httpx.Response(200, content=b"<gpx/>"))
    upload = mock_apis.post(f"{STRAVA}/uploads").mock(return_value=httpx.Response(201, json={"id": 77}))
    mock_apis.get(f"{STRAVA}/uploads/77").mock(
        return_value=httpx.Response(200, json={"id": 77, "activity_id": 555})
    )
    runner.run_cycle("test", tracks=False)
    assert upload.call_count == 1
    assert b"routepass-komoot-100" in upload.calls[0].request.content

    with session_scope() as db:
        job = db.scalar(select(SyncJob))
        assert job.status == "done" and job.target_id == "555"
        act = db.scalar(select(Activity))
        assert {s.provider for s in act.sources} == {"strava", "komoot"}

    # Strava now lists the uploaded copy: it links to the same activity, nothing re-uploads.
    _strava_list(mock_apis, [strava_activity(555, T0, external_id="routepass-komoot-100.gpx")])
    runner.run_cycle("test", tracks=False, full=True)
    assert upload.call_count == 1
    with session_scope() as db:
        assert db.scalar(select(func.count()).select_from(Activity)) == 1
        assert db.scalar(select(func.count()).select_from(SyncJob)) == 1


def test_rules_skip_and_rename(connected, mock_apis):
    _strava_list(
        mock_apis,
        [
            strava_activity(1, T0, km=40),
            strava_activity(2, T0 + days(1), km=5),
            strava_activity(3, T0 + days(2), km=20, sport_type="Run"),
        ],
    )
    _komoot_list(mock_apis, [])
    with session_scope() as db:
        store.update_preferences(db, {"sync": {"strava_to_komoot": {"enabled": True}}})
    runner.run_cycle("test", tracks=False)
    _age_records()

    client_rules = [
        {
            "name": "No short rides",
            "direction": "strava_to_komoot",
            "priority": 1,
            "conditions": {"families": ["ride"], "distance_km": {"max": 10}},
            "actions": {"skip": True},
        },
        {
            "name": "Rides",
            "direction": "strava_to_komoot",
            "priority": 2,
            "conditions": {"sports": ["Ride"]},
            "actions": {"name": "{name} · {distance_km:.0f} km", "komoot": {"visibility": "friends"}},
        },
        {
            "name": "Ignore runs",
            "direction": "strava_to_komoot",
            "priority": 3,
            "conditions": {"families": ["run"]},
            "actions": {"skip": True},
        },
    ]
    from routepass import services

    with session_scope() as db:
        for r in client_rules:
            services.save_rule(db, r)

    upload = mock_apis.post(f"{KOMOOT}/tours/").mock(return_value=httpx.Response(201, json={"id": 900}))
    patch = mock_apis.patch(f"{KOMOOT}/tours/900").mock(return_value=httpx.Response(200, json={}))
    mock_apis.get(re.compile(rf"{STRAVA}/activities/\d+/streams")).mock(
        return_value=httpx.Response(200, json=streams())
    )
    runner.run_cycle("test", tracks=False)

    assert upload.call_count == 1
    assert upload.calls[0].request.url.params["name"] == "Strava 1 · 40 km"
    assert upload.calls[0].request.url.params["sport"] == "touringbike"
    assert b'"status":"friends"' in patch.calls[0].request.content.replace(b" ", b"")
    with session_scope() as db:
        statuses = sorted(j.status for j in db.scalars(select(SyncJob)))
        assert statuses == ["done", "skipped", "skipped"]


def test_start_date_blocks_old_activities(connected, mock_apis):
    _strava_list(mock_apis, [strava_activity(1, T0)])
    _komoot_list(mock_apis, [])
    with session_scope() as db:
        store.update_preferences(
            db, {"sync": {"start_date": "2026-06-01", "strava_to_komoot": {"enabled": True}}}
        )
    runner.run_cycle("test", tracks=False)
    _age_records()
    runner.run_cycle("test", tracks=False)
    with session_scope() as db:
        assert db.scalar(select(func.count()).select_from(SyncJob)) == 0


def test_api_requires_token(client):
    assert client.get("/api/v1/status").status_code == 401
    assert client.get("/api/v1/status", headers=AUTH).status_code == 200
    assert client.get("/api/v1/health").status_code == 200
    assert client.post("/mcp", json={}).status_code == 401


def test_api_activities_and_insights(client, connected, mock_apis):
    _strava_list(mock_apis, [strava_activity(i, T0 + days(i), km=10 + i) for i in range(1, 15)])
    _komoot_list(mock_apis, [komoot_tour(100 + i, T0 + days(i), km=10 + i) for i in range(1, 5)])
    runner.run_cycle("test", tracks=False)

    r = client.get("/api/v1/activities", params={"per_page": 5, "sort": "distance"}, headers=AUTH).json()
    assert r["total"] == 14 and r["items"][0]["distance_m"] == 24000
    both = client.get("/api/v1/activities", params={"presence": "both"}, headers=AUTH).json()
    assert both["total"] == 4
    detail = client.get(f"/api/v1/activities/{r['items'][0]['id']}", headers=AUTH).json()
    assert detail["sources"][0]["provider"] == "strava"

    totals = client.get("/api/v1/insights/totals", headers=AUTH).json()
    assert totals["totals"]["count"] == 14
    assert client.get("/api/v1/insights/coverage", headers=AUTH).json()["duplicates_hidden"] == 4
    for path in (
        "dashboard",
        "timeseries",
        "calendar",
        "load",
        "records",
        "habits",
        "eddington",
        "heatmap",
        "cumulative",
        "power-curve",
    ):
        assert client.get(f"/api/v1/insights/{path}", headers=AUTH).status_code == 200, path


def test_rule_validation(client):
    bad = client.post(
        "/api/v1/rules",
        json={"name": "x", "direction": "strava_to_komoot", "conditions": {"nope": 1}, "actions": {}},
        headers=AUTH,
    )
    assert bad.status_code == 422
    ok = client.post(
        "/api/v1/rules",
        json={"name": "x", "direction": "strava_to_komoot", "conditions": {}, "actions": {"skip": True}},
        headers=AUTH,
    )
    assert ok.status_code == 201


def test_mcp_lists_and_calls_tools(client, connected, mock_apis):
    headers = {**AUTH, "Accept": "application/json, text/event-stream"}
    init = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "t", "version": "1"},
            },
        },
        headers=headers,
    )
    assert init.status_code == 200, init.text
    tools = client.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, headers=headers)
    names = {t["name"] for t in tools.json()["result"]["tools"]}
    assert {"list_activities", "get_training_load", "save_rule", "run_sync"} <= names
    call = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "get_status", "arguments": {}},
        },
        headers=headers,
    )
    assert call.status_code == 200 and "error" not in call.json(), call.text


def test_strava_webhook_verify_and_event(client, connected, monkeypatch):
    from routepass.config import get_settings
    from routepass.engine import runner
    from routepass.engine.clients import STRAVA_ATHLETE

    monkeypatch.setenv("ROUTEPASS_STRAVA_WEBHOOK_VERIFY_TOKEN", "vt")
    get_settings.cache_clear()
    ok = client.get(
        "/api/v1/webhooks/strava",
        params={"hub.mode": "subscribe", "hub.verify_token": "vt", "hub.challenge": "c1"},
    )
    assert ok.status_code == 200 and ok.json() == {"hub.challenge": "c1"}
    assert client.get("/api/v1/webhooks/strava", params={"hub.verify_token": "no"}).status_code == 403

    woken = []
    monkeypatch.setattr(runner, "trigger_soon", lambda delay_s=0: woken.append(delay_s))
    with session_scope() as db:
        store.set_value(db, STRAVA_ATHLETE, {"id": 77})
    event = {"object_type": "activity", "aspect_type": "create", "object_id": 5, "owner_id": 77}
    assert client.post("/api/v1/webhooks/strava", json=event).json()["accepted"] is True
    assert woken == [0, 660]
    assert client.post("/api/v1/webhooks/strava", json={**event, "owner_id": 1}).json()["accepted"] is False
    deauth = {
        "object_type": "athlete",
        "aspect_type": "update",
        "owner_id": 77,
        "updates": {"authorized": "false"},
    }
    client.post("/api/v1/webhooks/strava", json=deauth)
    with session_scope() as db:
        assert store.get_value(db, "strava.tokens") is None

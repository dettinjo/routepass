from __future__ import annotations

from datetime import date, timedelta

import numpy as np

from routepass import mcp_server
from routepass.analysis import track as trk


def _sample_gpx() -> str:
    # 12 km undulating trail route (~500m climbing)
    pts = []
    lat = 47.0
    for i in range(121):
        lat += 0.0009  # ~100 m per step
        ele = 500.0 + (i * 8.0 if i <= 60 else (120 - i) * 8.0)
        pts.append(f'<trkpt lat="{lat:.6f}" lon="8.000000"><ele>{ele:.1f}</ele></trkpt>')
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<gpx version="1.1"><trk><name>Test 12k</name><trkseg>' + "".join(pts) + "</trkseg></trk></gpx>"
    )


def test_minetti_gap_and_track_compute():
    assert abs(float(trk.minetti_gap_factor(0.0)) - 1.0) < 1e-6
    assert float(trk.minetti_gap_factor(0.10)) > 1.4
    assert float(trk.minetti_gap_factor(-0.08)) < 1.0

    n = 120
    t = np.arange(n, dtype="float64") * 10.0  # 20 min
    d = np.linspace(0.0, 3000.0, n)  # 3 km
    ele = np.linspace(500.0, 740.0, n)  # +240m climb (8% grade)
    nt = trk.NormalizedTrack(time_s=t, elevation_m=ele, distance_m=d)
    res = trk.compute(nt, family="run")
    assert res.summary["gap_speed_ms"] > res.summary["avg_speed_ms"]
    assert res.summary["effort_km"] > 5.0
    assert res.detail["splits"][0]["gap_speed_ms"] > res.detail["splits"][0]["speed_ms"]
    assert any(p.get("gap") is not None for p in res.points)


def test_trail_endpoints_and_mcp_tools(client):
    race_date = (date.today() + timedelta(days=35)).isoformat()
    updated = mcp_server.set_trail_race_goal(
        name="Alpine 50k",
        date=race_date,
        distance_km=50.0,
        elevation_gain_m=2400,
        weekly_km_target=65.0,
        weekly_vert_target=2000,
    )
    assert updated["name"] == "Alpine 50k"
    assert updated["distance_km"] == 50.0

    hdrs = {"Authorization": "Bearer test-token"}
    r = client.get("/api/v1/insights/trail", params={"weeks": 8}, headers=hdrs)
    assert r.status_code == 200
    body = r.json()
    assert body["race"]["phase"] == "peak"
    assert body["race"]["effort_km"] == 74.0
    assert len(body["weeks"]) == 8

    brief = mcp_server.get_trail_training_brief(weeks=6)
    assert brief["race"]["name"] == "Alpine 50k"
    assert len(brief["weeks"]) == 6

    gpx = _sample_gpx()
    rp = client.post(
        "/api/v1/insights/trail/race-plan",
        json={"gpx": gpx, "aid_stations_km": [6.0], "fade_pct": 8.0, "carbs_g_per_h": 70.0},
        headers=hdrs,
    )
    assert rp.status_code == 200
    plan = rp.json()
    assert plan["distance_km"] > 10.0
    assert plan["elevation_gain_m"] > 300
    assert len(plan["legs"]) == 2
    assert plan["total_carbs_g"] > 0

    mcp_plan = mcp_server.plan_trail_race_gpx(gpx, aid_stations_km=[6.0])
    assert mcp_plan["est_total_s"] == plan["est_total_s"]

    prompt = mcp_server.trail_coach_review("tapering")
    assert "get_trail_training_brief" in prompt
    assert "tapering" in prompt

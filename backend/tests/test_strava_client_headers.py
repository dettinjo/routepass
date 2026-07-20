from __future__ import annotations

import httpx

from app.services.strava import StravaClient


def test_capture_rate_limit_headers_stores_both_buckets():
    client = StravaClient(access_token="tok")
    resp = httpx.Response(
        200,
        headers={"X-RateLimit-Limit": "400,4000", "X-ReadRateLimit-Limit": "200,2000"},
    )
    client._capture_rate_limit_headers(resp)
    assert client.last_rate_limit_headers == {
        "X-RateLimit-Limit": "400,4000",
        "X-ReadRateLimit-Limit": "200,2000",
    }


def test_capture_rate_limit_headers_noop_when_absent():
    client = StravaClient(access_token="tok")
    resp = httpx.Response(200, headers={})
    client._capture_rate_limit_headers(resp)
    assert client.last_rate_limit_headers is None


def test_capture_rate_limit_headers_keeps_previous_on_missing_headers():
    """A response without the headers must not clobber a previously captured value."""
    client = StravaClient(access_token="tok")
    client._capture_rate_limit_headers(
        httpx.Response(200, headers={"X-RateLimit-Limit": "400,4000"})
    )
    client._capture_rate_limit_headers(httpx.Response(200, headers={}))
    assert client.last_rate_limit_headers == {"X-RateLimit-Limit": "400,4000"}

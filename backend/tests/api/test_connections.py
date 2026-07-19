from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def _mock_komoot_client(status_code: int, username: str = "123456789") -> MagicMock:
    """Build a mocked httpx.AsyncClient whose GET returns the given Komoot response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.is_success = 200 <= status_code < 300
    resp.json.return_value = {"username": username}

    client = AsyncMock()
    client.__aenter__.return_value = client
    client.__aexit__.return_value = None
    client.get.return_value = resp
    return client


@pytest.mark.asyncio
async def test_list_connections_empty(
    async_client: AsyncClient,
    free_user_headers: dict[str, str],
) -> None:
    """A new user has no connections."""
    response = await async_client.get("/api/v1/connections", headers=free_user_headers)
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_create_and_list_connection(
    async_client: AsyncClient,
    free_user_headers: dict[str, str],
) -> None:
    """Creating a connection returns it in the list."""
    payload = {
        "platform": "strava",
        "display_name": "My Strava",
        "credentials": {"api_key": "secret"},
    }
    create_resp = await async_client.post(
        "/api/v1/connections", json=payload, headers=free_user_headers
    )
    assert create_resp.status_code == 201
    data = create_resp.json()
    assert data["platform"] == "strava"
    assert data["display_name"] == "My Strava"
    assert "id" in data
    conn_id = data["id"]

    list_resp = await async_client.get("/api/v1/connections", headers=free_user_headers)
    assert list_resp.status_code == 200
    ids = [c["id"] for c in list_resp.json()]
    assert conn_id in ids


@pytest.mark.asyncio
async def test_get_connection_by_id(
    async_client: AsyncClient,
    free_user_headers: dict[str, str],
) -> None:
    """GET /connections/{id} returns the specific connection."""
    create_resp = await async_client.post(
        "/api/v1/connections",
        json={"platform": "komoot", "display_name": "Komoot Account"},
        headers=free_user_headers,
    )
    conn_id = create_resp.json()["id"]

    get_resp = await async_client.get(f"/api/v1/connections/{conn_id}", headers=free_user_headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == conn_id
    assert get_resp.json()["platform"] == "komoot"


@pytest.mark.asyncio
async def test_get_connection_not_found(
    async_client: AsyncClient,
    free_user_headers: dict[str, str],
) -> None:
    """Non-existent connection ID returns 404."""
    response = await async_client.get(
        "/api/v1/connections/00000000-0000-0000-0000-000000000000",
        headers=free_user_headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_connection(
    async_client: AsyncClient,
    free_user_headers: dict[str, str],
) -> None:
    """Deleting a connection removes it from the list."""
    create_resp = await async_client.post(
        "/api/v1/connections",
        json={"platform": "intervals_icu", "display_name": "Intervals"},
        headers=free_user_headers,
    )
    conn_id = create_resp.json()["id"]

    del_resp = await async_client.delete(
        f"/api/v1/connections/{conn_id}", headers=free_user_headers
    )
    assert del_resp.status_code == 204

    list_resp = await async_client.get("/api/v1/connections", headers=free_user_headers)
    ids = [c["id"] for c in list_resp.json()]
    assert conn_id not in ids


@pytest.mark.asyncio
async def test_delete_connection_not_found(
    async_client: AsyncClient,
    free_user_headers: dict[str, str],
) -> None:
    """Deleting a non-existent connection returns 404."""
    response = await async_client.delete(
        "/api/v1/connections/00000000-0000-0000-0000-000000000000",
        headers=free_user_headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_connection_invalid_platform(
    async_client: AsyncClient,
    free_user_headers: dict[str, str],
) -> None:
    """An unknown platform name is rejected with 422."""
    response = await async_client.post(
        "/api/v1/connections",
        json={"platform": "nonexistent", "display_name": "Bad Platform"},
        headers=free_user_headers,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_connections_isolated_between_users(
    async_client: AsyncClient,
    free_user_headers: dict[str, str],
    pro_user_headers: dict[str, str],
) -> None:
    """Users can only see their own connections."""
    await async_client.post(
        "/api/v1/connections",
        json={"platform": "strava", "display_name": "Free user's Strava"},
        headers=free_user_headers,
    )

    pro_resp = await async_client.get("/api/v1/connections", headers=pro_user_headers)
    assert pro_resp.status_code == 200
    assert pro_resp.json() == []


@pytest.mark.asyncio
async def test_create_komoot_connection_validates_and_encrypts(
    async_client: AsyncClient,
    free_user_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    """Komoot connect needs only email+password: the API auto-discovers the user_id
    and stores the credentials encrypted (never as plaintext)."""
    from app.core.security import decrypt
    from app.db.models.connection import Connection

    with patch(
        "app.api.v1.connections.httpx.AsyncClient",
        return_value=_mock_komoot_client(200, username="987654321"),
    ):
        resp = await async_client.post(
            "/api/v1/connections",
            json={
                "platform": "komoot",
                "display_name": "My Komoot",
                "credentials": {"email": "rider@example.com", "password": "s3cret"},
            },
            headers=free_user_headers,
        )

    assert resp.status_code == 201
    assert resp.json()["platform"] == "komoot"

    conn = (
        await db.execute(select(Connection).where(Connection.platform == "komoot"))
    ).scalar_one()
    assert conn.credentials_enc is not None
    assert b"s3cret" not in conn.credentials_enc  # encrypted at rest
    creds = json.loads(decrypt(conn.credentials_enc))
    assert creds["user_id"] == "987654321"  # auto-discovered
    assert creds["email"] == "rider@example.com"


@pytest.mark.asyncio
async def test_create_komoot_connection_rejects_bad_credentials(
    async_client: AsyncClient,
    free_user_headers: dict[str, str],
) -> None:
    """Wrong Komoot email/password is rejected at connect time with a 400."""
    with patch(
        "app.api.v1.connections.httpx.AsyncClient",
        return_value=_mock_komoot_client(401),
    ):
        resp = await async_client.post(
            "/api/v1/connections",
            json={
                "platform": "komoot",
                "display_name": "My Komoot",
                "credentials": {"email": "rider@example.com", "password": "wrong"},
            },
            headers=free_user_headers,
        )

    assert resp.status_code == 400
    assert "Invalid Komoot" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_delete_strava_connection_revokes_token(
    async_client: AsyncClient,
    free_user,
    free_user_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    """Disconnecting Strava via the connections page must also delete the StravaToken,
    otherwise the worker keeps pushing activities and /me still reports it connected."""
    from app.db.models.connection import Connection
    from app.db.models.user import StravaApp, StravaToken

    db.add(
        StravaApp(
            id=1,
            client_id="12345",
            client_secret=b"enc-secret",
            display_name="Test App",
            is_active=True,
        )
    )
    conn = Connection(user_id=free_user.id, platform="strava", display_name="athlete_1")
    db.add(conn)
    from datetime import UTC, datetime, timedelta

    db.add(
        StravaToken(
            user_id=free_user.id,
            strava_app_id=1,
            strava_athlete_id=42,
            access_token=b"enc",
            refresh_token=b"enc",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            connected_at=datetime.now(UTC),
        )
    )
    await db.commit()
    await db.refresh(conn)

    # Sanity: /me sees Strava as connected (token-derived)
    me = (await async_client.get("/api/v1/auth/me", headers=free_user_headers)).json()
    assert me["strava_connected"] is True

    del_resp = await async_client.delete(
        f"/api/v1/connections/{conn.id}", headers=free_user_headers
    )
    assert del_resp.status_code == 204

    token = (
        await db.execute(select(StravaToken).where(StravaToken.user_id == free_user.id))
    ).scalar_one_or_none()
    assert token is None  # token revoked, not orphaned

    me_after = (await async_client.get("/api/v1/auth/me", headers=free_user_headers)).json()
    assert me_after["strava_connected"] is False


@pytest.mark.asyncio
async def test_list_connections_surfaces_last_error(
    async_client: AsyncClient,
    free_user,
    free_user_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    """A failed sync (e.g. Komoot password changed) surfaces last_error in the API."""
    from app.db.models.connection import Connection
    from app.db.models.sync import ConnectionSyncState

    conn = Connection(
        user_id=free_user.id, platform="komoot", display_name="Komoot", status="error"
    )
    db.add(conn)
    await db.commit()
    await db.refresh(conn)
    db.add(
        ConnectionSyncState(
            connection_id=conn.id,
            user_id=free_user.id,
            last_error="Invalid Komoot email or password.",
        )
    )
    await db.commit()

    resp = await async_client.get("/api/v1/connections", headers=free_user_headers)
    assert resp.status_code == 200
    komoot = next(c for c in resp.json() if c["platform"] == "komoot")
    assert komoot["status"] == "error"
    assert komoot["last_error"] == "Invalid Komoot email or password."


@pytest.mark.asyncio
async def test_list_connections_last_error_null_when_healthy(
    async_client: AsyncClient,
    free_user_headers: dict[str, str],
) -> None:
    """A connection with no sync-state row reports last_error=None (no crash on join)."""
    await async_client.post(
        "/api/v1/connections",
        json={"platform": "strava", "display_name": "My Strava"},
        headers=free_user_headers,
    )
    resp = await async_client.get("/api/v1/connections", headers=free_user_headers)
    assert resp.status_code == 200
    assert resp.json()[0]["last_error"] is None


@pytest.mark.asyncio
async def test_source_connection_exposes_poll_interval(
    async_client: AsyncClient,
    free_user_headers: dict[str, str],
) -> None:
    """A source platform (komoot) reports poll-interval bounds; strava does not."""
    with patch(
        "app.api.v1.connections.httpx.AsyncClient",
        return_value=_mock_komoot_client(200),
    ):
        await async_client.post(
            "/api/v1/connections",
            json={
                "platform": "komoot",
                "display_name": "Komoot",
                "credentials": {"email": "r@e.com", "password": "p"},
            },
            headers=free_user_headers,
        )
    await async_client.post(
        "/api/v1/connections",
        json={"platform": "strava", "display_name": "Strava"},
        headers=free_user_headers,
    )
    conns = (await async_client.get("/api/v1/connections", headers=free_user_headers)).json()
    komoot = next(c for c in conns if c["platform"] == "komoot")
    strava = next(c for c in conns if c["platform"] == "strava")

    assert komoot["is_source"] is True
    assert komoot["poll_interval"]["default"] == 120
    assert komoot["poll_interval"]["min"] == 30
    assert komoot["poll_interval"]["effective"] == 120  # unset → default
    assert komoot["poll_interval"]["configured"] is None

    assert strava["is_source"] is False
    assert strava["poll_interval"] is None


@pytest.mark.asyncio
async def test_update_poll_interval(
    async_client: AsyncClient,
    free_user_headers: dict[str, str],
) -> None:
    """Setting a valid interval sticks; below the platform minimum is rejected."""
    with patch(
        "app.api.v1.connections.httpx.AsyncClient",
        return_value=_mock_komoot_client(200),
    ):
        create = await async_client.post(
            "/api/v1/connections",
            json={
                "platform": "komoot",
                "display_name": "Komoot",
                "credentials": {"email": "r@e.com", "password": "p"},
            },
            headers=free_user_headers,
        )
    conn_id = create.json()["id"]

    ok = await async_client.patch(
        f"/api/v1/connections/{conn_id}",
        json={"poll_interval_min": 45},
        headers=free_user_headers,
    )
    assert ok.status_code == 200
    assert ok.json()["poll_interval"]["configured"] == 45
    assert ok.json()["poll_interval"]["effective"] == 45

    too_fast = await async_client.patch(
        f"/api/v1/connections/{conn_id}",
        json={"poll_interval_min": 5},
        headers=free_user_headers,
    )
    assert too_fast.status_code == 422
    assert "between 30" in too_fast.json()["detail"]


@pytest.mark.asyncio
async def test_update_poll_interval_rejected_for_non_source(
    async_client: AsyncClient,
    free_user_headers: dict[str, str],
) -> None:
    """Strava is webhook-driven, not polled — interval isn't configurable."""
    create = await async_client.post(
        "/api/v1/connections",
        json={"platform": "strava", "display_name": "Strava"},
        headers=free_user_headers,
    )
    conn_id = create.json()["id"]
    resp = await async_client.patch(
        f"/api/v1/connections/{conn_id}",
        json={"poll_interval_min": 60},
        headers=free_user_headers,
    )
    assert resp.status_code == 422
    assert "not configurable" in resp.json()["detail"]

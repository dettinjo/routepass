from __future__ import annotations

import pytest
from httpx import AsyncClient


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

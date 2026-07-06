from __future__ import annotations

import pytest
from httpx import AsyncClient


async def _make_connection(
    async_client: AsyncClient,
    headers: dict[str, str],
    platform: str,
    display_name: str,
) -> str:
    """Helper: create a connection and return its id."""
    resp = await async_client.post(
        "/api/v1/connections",
        json={"platform": platform, "display_name": display_name},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_list_pipelines_empty(
    async_client: AsyncClient,
    free_user_headers: dict[str, str],
) -> None:
    """A new user has no pipelines."""
    response = await async_client.get("/api/v1/pipelines", headers=free_user_headers)
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_create_and_list_pipeline(
    async_client: AsyncClient,
    free_user_headers: dict[str, str],
) -> None:
    """Creating a pipeline with two valid connections succeeds."""
    src_id = await _make_connection(async_client, free_user_headers, "komoot", "Komoot")
    dst_id = await _make_connection(async_client, free_user_headers, "strava", "Strava")

    create_resp = await async_client.post(
        "/api/v1/pipelines",
        json={
            "source_connection_id": src_id,
            "dest_connection_id": dst_id,
            "name": "Komoot → Strava",
        },
        headers=free_user_headers,
    )
    assert create_resp.status_code == 201
    data = create_resp.json()
    assert data["name"] == "Komoot → Strava"
    assert data["source_connection_id"] == src_id
    assert data["dest_connection_id"] == dst_id
    assert data["enabled"] is True
    pipeline_id = data["id"]

    list_resp = await async_client.get("/api/v1/pipelines", headers=free_user_headers)
    assert list_resp.status_code == 200
    ids = [p["id"] for p in list_resp.json()]
    assert pipeline_id in ids


@pytest.mark.asyncio
async def test_create_pipeline_invalid_connection(
    async_client: AsyncClient,
    free_user_headers: dict[str, str],
) -> None:
    """Pipeline creation with a non-existent connection returns 404."""
    src_id = await _make_connection(async_client, free_user_headers, "komoot", "Komoot")

    response = await async_client.post(
        "/api/v1/pipelines",
        json={
            "source_connection_id": src_id,
            "dest_connection_id": "00000000-0000-0000-0000-000000000000",
            "name": "Bad pipeline",
        },
        headers=free_user_headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_pipeline_by_id(
    async_client: AsyncClient,
    free_user_headers: dict[str, str],
) -> None:
    """GET /pipelines/{id} returns the specific pipeline."""
    src_id = await _make_connection(async_client, free_user_headers, "komoot", "Komoot")
    dst_id = await _make_connection(async_client, free_user_headers, "strava", "Strava")

    create_resp = await async_client.post(
        "/api/v1/pipelines",
        json={"source_connection_id": src_id, "dest_connection_id": dst_id, "name": "K→S"},
        headers=free_user_headers,
    )
    pipeline_id = create_resp.json()["id"]

    get_resp = await async_client.get(f"/api/v1/pipelines/{pipeline_id}", headers=free_user_headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == pipeline_id


@pytest.mark.asyncio
async def test_get_pipeline_not_found(
    async_client: AsyncClient,
    free_user_headers: dict[str, str],
) -> None:
    """Non-existent pipeline ID returns 404."""
    response = await async_client.get(
        "/api/v1/pipelines/00000000-0000-0000-0000-000000000000",
        headers=free_user_headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_pipeline_enabled(
    async_client: AsyncClient,
    free_user_headers: dict[str, str],
) -> None:
    """PATCH /pipelines/{id} can toggle enabled and rename."""
    src_id = await _make_connection(async_client, free_user_headers, "komoot", "Komoot")
    dst_id = await _make_connection(async_client, free_user_headers, "strava", "Strava")

    create_resp = await async_client.post(
        "/api/v1/pipelines",
        json={"source_connection_id": src_id, "dest_connection_id": dst_id, "name": "Original"},
        headers=free_user_headers,
    )
    pipeline_id = create_resp.json()["id"]

    patch_resp = await async_client.patch(
        f"/api/v1/pipelines/{pipeline_id}",
        json={"enabled": False, "name": "Updated"},
        headers=free_user_headers,
    )
    assert patch_resp.status_code == 200
    updated = patch_resp.json()
    assert updated["enabled"] is False
    assert updated["name"] == "Updated"


@pytest.mark.asyncio
async def test_delete_pipeline(
    async_client: AsyncClient,
    free_user_headers: dict[str, str],
) -> None:
    """Deleting a pipeline removes it."""
    src_id = await _make_connection(async_client, free_user_headers, "komoot", "Komoot")
    dst_id = await _make_connection(async_client, free_user_headers, "strava", "Strava")

    create_resp = await async_client.post(
        "/api/v1/pipelines",
        json={"source_connection_id": src_id, "dest_connection_id": dst_id, "name": "Temp"},
        headers=free_user_headers,
    )
    pipeline_id = create_resp.json()["id"]

    del_resp = await async_client.delete(
        f"/api/v1/pipelines/{pipeline_id}", headers=free_user_headers
    )
    assert del_resp.status_code == 204

    list_resp = await async_client.get("/api/v1/pipelines", headers=free_user_headers)
    ids = [p["id"] for p in list_resp.json()]
    assert pipeline_id not in ids


@pytest.mark.asyncio
async def test_delete_pipeline_not_found(
    async_client: AsyncClient,
    free_user_headers: dict[str, str],
) -> None:
    """Deleting a non-existent pipeline returns 404."""
    response = await async_client.delete(
        "/api/v1/pipelines/00000000-0000-0000-0000-000000000000",
        headers=free_user_headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_pipelines_isolated_between_users(
    async_client: AsyncClient,
    free_user_headers: dict[str, str],
    pro_user_headers: dict[str, str],
) -> None:
    """Users can only see their own pipelines."""
    src_id = await _make_connection(async_client, free_user_headers, "komoot", "Komoot")
    dst_id = await _make_connection(async_client, free_user_headers, "strava", "Strava")
    await async_client.post(
        "/api/v1/pipelines",
        json={"source_connection_id": src_id, "dest_connection_id": dst_id, "name": "Free user's"},
        headers=free_user_headers,
    )

    pro_resp = await async_client.get("/api/v1/pipelines", headers=pro_user_headers)
    assert pro_resp.status_code == 200
    assert pro_resp.json() == []

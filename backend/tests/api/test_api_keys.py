from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient

from app.db.models.subscription import ApiKey
from app.db.models.user import User

UTC = UTC


@pytest.mark.asyncio
async def test_create_and_list_api_keys(async_client: AsyncClient):
    """Test generating a new API key and listing them."""
    from app.api import deps
    from app.db.models.subscription import Subscription
    from app.main import app

    fake_user = User(id="00000000-0000-0000-0000-000000000000", is_active=True)
    fake_sub = Subscription(user_id=fake_user.id, tier="pro", status="active")

    # Override get_current_user to skip JWT validation
    app.dependency_overrides[deps.get_current_user] = lambda: fake_user

    mock_db_state: list = []  # api keys stored here

    class FakeResult:
        def __init__(self, scalar_val=None, items=None):
            self._scalar = scalar_val
            self._items = items if items is not None else []

        def scalar_one_or_none(self):
            return self._scalar

        def scalars(self):
            items = self._items

            class _S:
                def all(self):
                    return items

            return _S()

    class FakeDB:
        async def execute(self, stmt):
            stmt_str = str(stmt).lower()
            if "subscriptions" in stmt_str:
                return FakeResult(scalar_val=fake_sub)
            if "api_keys" in stmt_str:
                # Only return ApiKey rows — audit log rows also land in mock_db_state
                return FakeResult(items=[o for o in mock_db_state if isinstance(o, ApiKey)])
            return FakeResult()

        def add(self, obj):
            if not getattr(obj, "created_at", None):
                obj.created_at = datetime.now(UTC)
            mock_db_state.append(obj)

        async def flush(self):
            pass

        async def commit(self):
            pass

    app.dependency_overrides[deps.get_db] = lambda: FakeDB()

    # Create key
    response = await async_client.post("/api/v1/api-keys", json={"name": "Zapier Integration"})

    assert response.status_code == 200
    data = response.json()
    assert "raw_key" in data
    assert data["raw_key"].startswith("rp_")
    assert data["name"] == "Zapier Integration"

    # List keys
    response_list = await async_client.get("/api/v1/api-keys")
    assert response_list.status_code == 200
    list_data = response_list.json()
    assert len(list_data["data"]) == 1
    assert list_data["data"][0]["name"] == "Zapier Integration"

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_revoke_api_key(async_client: AsyncClient):
    """Test revoking an existing API key."""
    from app.api import deps
    from app.db.models.subscription import Subscription
    from app.main import app

    fake_user = User(id="00000000-0000-0000-0000-000000000000", is_active=True)
    fake_sub = Subscription(user_id=fake_user.id, tier="pro", status="active")
    existing_key = ApiKey(
        id="11111111-1111-1111-1111-111111111111",
        user_id=fake_user.id,
        key_hash="abc",
        key_prefix="rp_test...",
        name="Integration",
    )

    app.dependency_overrides[deps.get_current_user] = lambda: fake_user

    class FakeResult:
        def __init__(self, scalar_val=None):
            self._scalar = scalar_val

        def scalar_one_or_none(self):
            return self._scalar

    class FakeDB:
        async def execute(self, stmt):
            stmt_str = str(stmt).lower()
            if "subscriptions" in stmt_str:
                return FakeResult(scalar_val=fake_sub)
            return FakeResult(scalar_val=existing_key)

        def add(self, obj):
            pass

        async def flush(self):
            pass

        async def commit(self):
            pass

    app.dependency_overrides[deps.get_db] = lambda: FakeDB()

    response = await async_client.delete(f"/api/v1/api-keys/{existing_key.id}")

    assert response.status_code == 200
    assert existing_key.revoked_at is not None

    app.dependency_overrides.clear()

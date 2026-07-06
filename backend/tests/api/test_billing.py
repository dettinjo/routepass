from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from httpx import AsyncClient

from app.db.models.subscription import Subscription
from app.db.models.user import User

UTC = timezone.utc


@pytest.mark.asyncio
async def test_checkout_endpoint(async_client: AsyncClient):
    """Test generating a Stripe Checkout Session."""
    from app.api import deps
    from app.core.config import settings
    from app.main import app

    # We must patch the settings temporarily so billing thinks it's configured
    settings.STRIPE_SECRET_KEY = "sk_test_fake"
    settings.STRIPE_PRICE_PRO = "price_fake123"

    fake_user = User(id="00000000-0000-0000-0000-000000000000", email="test@test.com")

    app.dependency_overrides[deps.get_current_user] = lambda: fake_user

    class FakeDB:
        async def execute(self, stmt):
            pass

    app.dependency_overrides[deps.get_db] = lambda: FakeDB()

    with patch("stripe.checkout.Session.create") as mock_create:

        class FakeSession:
            url = "https://checkout.stripe.com/fake_url"

        mock_create.return_value = FakeSession()

        response = await async_client.post("/api/v1/billing/checkout", json={"tier": "pro"})

        assert response.status_code == 200
        assert "url" in response.json()
        assert response.json()["url"] == "https://checkout.stripe.com/fake_url"

        # Verify it passed the right price ID mapped from "pro"
        mock_create.assert_called_once()
        call_args = mock_create.call_args[1]
        assert call_args["line_items"][0]["price"] == "price_fake123"
        assert call_args["client_reference_id"] == "00000000-0000-0000-0000-000000000000"

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_subscription_status(async_client: AsyncClient):
    """Test retrieving the current subscription info."""
    from app.api import deps
    from app.main import app

    fake_user = User(id="00000000-0000-0000-0000-000000000000", email="test@test.com")
    fake_sub = Subscription(
        user_id=fake_user.id,
        tier="pro",
        status="active",
        stripe_customer_id="cus_123",
        stripe_subscription_id="sub_123",
        current_period_end=datetime.now(UTC),
        activities_synced_this_period=7,
    )

    app.dependency_overrides[deps.get_current_user] = lambda: fake_user

    class FakeResult:
        def __init__(self, scalar_val=None):
            self._scalar = scalar_val

        def scalar_one_or_none(self):
            return self._scalar

    class FakeDB:
        async def execute(self, stmt):
            return FakeResult(scalar_val=fake_sub)

    app.dependency_overrides[deps.get_db] = lambda: FakeDB()

    response = await async_client.get("/api/v1/billing/subscription")

    assert response.status_code == 200
    data = response.json()
    assert data["tier"] == "pro"
    assert data["status"] == "active"
    assert data["stripe_customer_id"] == "cus_123"
    assert data["activities_synced_this_period"] == 7

    app.dependency_overrides.clear()

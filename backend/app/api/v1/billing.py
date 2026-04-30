from __future__ import annotations

import logging
from typing import Any

import stripe
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.core.config import settings
from app.db.models.subscription import Subscription
from app.db.models.user import User

logger = logging.getLogger(__name__)

stripe.api_key = settings.STRIPE_SECRET_KEY

router = APIRouter(tags=["billing"])


class CheckoutRequest(BaseModel):
    tier: str = "pro"


@router.get("/subscription")
async def get_subscription_status(
    user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_db),
) -> dict[str, Any]:
    """Return the current subscription information for the authenticated user."""
    stmt = select(Subscription).where(Subscription.user_id == user.id)
    result = await db.execute(stmt)
    sub = result.scalar_one_or_none()

    if not sub:
        return {
            "tier": "free",
            "status": "active",
            "stripe_customer_id": None,
            "stripe_subscription_id": None,
            "current_period_start": None,
            "current_period_end": None,
            "trial_ends_at": None,
            "canceled_at": None,
            "activities_synced_this_period": 0,
        }

    return {
        "tier": sub.tier,
        "status": sub.status,
        "stripe_customer_id": sub.stripe_customer_id,
        "stripe_subscription_id": sub.stripe_subscription_id,
        "current_period_start": sub.current_period_start.isoformat()
        if sub.current_period_start
        else None,
        "current_period_end": sub.current_period_end.isoformat()
        if sub.current_period_end
        else None,
        "trial_ends_at": sub.trial_ends_at.isoformat() if sub.trial_ends_at else None,
        "canceled_at": sub.canceled_at.isoformat() if sub.canceled_at else None,
        "activities_synced_this_period": sub.activities_synced_this_period,
    }


@router.post("/checkout")
async def create_checkout_session(
    payload: CheckoutRequest,
    user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_db),
) -> dict[str, str]:
    """Create a Stripe Checkout Session for subscription upgrade."""
    if settings.DEPLOYMENT_MODE == "selfhosted":
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Billing is not available in self-hosted mode.",
        )

    if payload.tier == "pro":
        price_id = settings.STRIPE_PRICE_PRO
        checkout_mode = "subscription"
    elif payload.tier == "lifetime":
        price_id = settings.STRIPE_PRICE_LIFETIME
        checkout_mode = "payment"
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid subscription tier.")

    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Billing is not configured.")

    if not price_id:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "Target pricing tier is not configured."
        )

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[
                {
                    "price": price_id,
                    "quantity": 1,
                },
            ],
            mode=checkout_mode,
            success_url=f"{settings.FRONTEND_URL}/settings?setup=success",
            cancel_url=f"{settings.FRONTEND_URL}/settings?setup=canceled",
            client_reference_id=str(user.id),
            customer_email=user.email,
        )
        return {"url": session.url}
    except Exception as e:
        logger.error("Checkout session creation failed for user %s: %s", user.id, e)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "Could not generate checkout session."
        ) from e


@router.post("/portal")
async def create_portal_session(
    user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_db),
) -> dict[str, str]:
    """Create a Stripe Customer Portal session."""
    if settings.DEPLOYMENT_MODE == "selfhosted":
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Billing is not available in self-hosted mode.",
        )

    stmt = select(Subscription).where(Subscription.user_id == user.id)
    result = await db.execute(stmt)
    sub = result.scalar_one_or_none()

    if not sub or not sub.stripe_customer_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "You do not have an active billing account yet."
        )

    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Billing is not configured.")

    try:
        session = stripe.billing_portal.Session.create(
            customer=sub.stripe_customer_id,
            return_url=f"{settings.FRONTEND_URL}/settings",
        )
        return {"url": session.url}
    except Exception as e:
        logger.error("Portal session creation failed for user %s: %s", user.id, e)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "Could not generate portal session."
        ) from e

from __future__ import annotations

import logging
from datetime import UTC, datetime

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.core.config import settings
from app.db.models.subscription import Subscription

UTC = UTC

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webhooks"])

stripe.api_key = settings.STRIPE_SECRET_KEY


@router.post("/stripe")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None),
    db: AsyncSession = Depends(deps.get_db),  # we need a non-auth db dependency
) -> dict:
    """Receive asynchronous events directly from Stripe."""
    if settings.DEPLOYMENT_MODE == "selfhosted":
        return {"status": "success"}

    if not settings.STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Webhooks are not configured.")

    payload = await request.body()

    try:
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, settings.STRIPE_WEBHOOK_SECRET
        )
    except ValueError as e:
        logger.error("Invalid payload in Stripe webhook: %s", e)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid payload") from e
    except stripe.error.SignatureVerificationError as e:
        logger.error("Invalid signature in Stripe webhook: %s", e)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid signature") from e

    # 1. Checkout Session Completed
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]

        user_id = session.get("client_reference_id")
        if not user_id:
            logger.warning("No client_reference_id found on checkout session %s", session.get("id"))
            return {"status": "ignored"}

        stripe_customer_id = session.get("customer")
        stripe_subscription_id = session.get("subscription")

        # Find or create subscription for this user
        stmt = select(Subscription).where(Subscription.user_id == user_id)
        result = await db.execute(stmt)
        sub = result.scalar_one_or_none()

        if not sub:
            sub = Subscription(user_id=user_id)
            db.add(sub)

        sub.stripe_customer_id = stripe_customer_id
        sub.stripe_subscription_id = stripe_subscription_id
        sub.status = "active"

        # Determine tier: one-time payment (mode=payment) → lifetime; recurring → pro.
        mode = session.get("mode")
        if mode == "payment":
            sub.tier = "lifetime"
        else:
            sub.tier = "pro"

        await db.commit()
        logger.info(
            "Activated %s subscription for user %s via checkout webhook.", sub.tier, user_id
        )

    # 2. Subscription Updated / Canceled
    elif event["type"] in ["customer.subscription.deleted", "customer.subscription.updated"]:
        subscription_obj = event["data"]["object"]
        customer_id = subscription_obj.get("customer")

        stmt = select(Subscription).where(Subscription.stripe_customer_id == customer_id)
        result = await db.execute(stmt)
        sub = result.scalar_one_or_none()

        if sub:
            if event["type"] == "customer.subscription.deleted":
                sub.status = "canceled"
                sub.tier = "free"
                sub.canceled_at = datetime.now(UTC)
                logger.info("Subscription canceled for customer %s.", customer_id)
            await db.commit()

    return {"status": "success"}


@router.get("/strava")
async def verify_strava_webhook(
    request: Request,
    hub_mode: str = "subscribe",
    hub_challenge: str = "",
    hub_verify_token: str = "",
) -> dict:
    """Verify the Strava webhook subscription challenge."""
    if hub_verify_token != settings.STRAVA_WEBHOOK_VERIFY_TOKEN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid verify token")
    return {"hub.challenge": hub_challenge}


@router.post("/strava")
async def receive_strava_webhook(
    request: Request,
    db: AsyncSession = Depends(deps.get_db),
) -> dict:
    """Receive pushed activity events from Strava."""
    payload = await request.json()

    object_type = payload.get("object_type")
    aspect_type = payload.get("aspect_type")
    object_id = payload.get("object_id")
    owner_id = payload.get("owner_id")

    if object_type == "activity" and aspect_type == "create":
        logger.info("Strava Webhook: Received new activity %s for athlete %s", object_id, owner_id)

        # We process this in the background since it might take time
        arq_pool = request.app.state.arq_pool
        if arq_pool:
            # owner_id is the Strava athlete id, not our local user primary key.
            await arq_pool.enqueue_job("process_strava_activity", str(owner_id), str(object_id))

    return {"status": "success"}

"""Subscription plan catalog + operator (comp) helpers.

Single source of truth for the billable plans so the pricing page, checkout and
webhook all agree. Prices are grounded in the dominant API cost: Strava Standard is
$11.99/mo per developer for a 10-athlete app, i.e. ~$1.20/athlete-slot/month, so any
paid plan comfortably covers a user's marginal cost with margin.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import settings


@dataclass(frozen=True)
class Plan:
    id: str  # stable plan id used by checkout
    name: str
    tier: str  # subscription tier granted (free / pro / lifetime)
    interval: str  # "month" | "year" | "once" | "free"
    amount_cents: int
    currency: str
    stripe_price_attr: str  # settings attribute holding the Stripe price id

    @property
    def checkout_mode(self) -> str:
        return "payment" if self.interval == "once" else "subscription"


CURRENCY = "usd"

PLANS: dict[str, Plan] = {
    "free": Plan("free", "Free", "free", "free", 0, CURRENCY, ""),
    "pro_monthly": Plan(
        "pro_monthly", "Pro Monthly", "pro", "month", 499, CURRENCY, "STRIPE_PRICE_PRO_MONTHLY"
    ),
    "pro_annual": Plan(
        "pro_annual", "Pro Annual", "pro", "year", 3900, CURRENCY, "STRIPE_PRICE_PRO_ANNUAL"
    ),
    "lifetime": Plan(
        "lifetime", "Lifetime", "lifetime", "once", 9900, CURRENCY, "STRIPE_PRICE_LIFETIME"
    ),
}


def stripe_price_for(plan: Plan) -> str:
    """Resolve the configured Stripe price id for a plan (falls back to legacy PRO)."""
    price = getattr(settings, plan.stripe_price_attr, "") if plan.stripe_price_attr else ""
    if not price and plan.id == "pro_annual":
        price = settings.STRIPE_PRICE_PRO  # legacy single-price config
    return price


def billing_configured() -> bool:
    return settings.DEPLOYMENT_MODE == "cloud" and bool(settings.STRIPE_SECRET_KEY)


def admin_emails() -> set[str]:
    return {e.strip().lower() for e in settings.ADMIN_EMAILS.split(",") if e.strip()}


def is_comp_email(email: str | None) -> bool:
    """True if this email is an operator/admin comped to the top tier."""
    return bool(email) and email.lower() in admin_emails()

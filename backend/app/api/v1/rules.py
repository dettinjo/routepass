from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.db.models.subscription import Subscription
from app.db.models.sync import SyncRule
from app.db.models.user import User

_RULE_LIMIT: dict[str, int] = {"free": 1, "pro": 5, "lifetime": 5, "business": 5}

# Valid direction pattern: "both" or "<platform>_to_<platform>" (e.g. strava_to_intervals_icu)
_DIRECTION_RE = re.compile(r"^[a-z][a-z_]*_to_[a-z][a-z_]*$")

router = APIRouter(tags=["rules"])


class RuleCreate(BaseModel):
    name: str
    direction: str
    conditions: dict
    actions: dict
    rule_order: int = 0
    is_active: bool = True


def _validate_direction(direction: str) -> None:
    if direction != "both" and not _DIRECTION_RE.match(direction):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Invalid direction — must be 'both' or '<platform>_to_<platform>'.",
        )


@router.get("")
async def list_rules(
    user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_db),
) -> dict[str, Any]:
    """List all sync rules for the current user."""
    stmt = select(SyncRule).where(SyncRule.user_id == user.id).order_by(SyncRule.rule_order.asc())
    result = await db.execute(stmt)
    rules = result.scalars().all()

    return {
        "data": [
            {
                "id": str(r.id),
                "name": r.name,
                "is_active": r.is_active,
                "direction": r.direction,
                "rule_order": r.rule_order,
                "conditions": r.conditions,
                "actions": r.actions,
            }
            for r in rules
        ]
    }


async def _get_tier(user: User, db: AsyncSession) -> str:
    sub = (
        await db.execute(select(Subscription).where(Subscription.user_id == user.id))
    ).scalar_one_or_none()
    return sub.tier if sub else "free"


@router.post("")
async def create_rule(
    payload: RuleCreate,
    user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_db),
) -> dict[str, Any]:
    """Create a new sync filtering rule."""
    _validate_direction(payload.direction)

    tier = await _get_tier(user, db)
    limit = _RULE_LIMIT.get(tier, 1)

    existing_count = len(
        (await db.execute(select(SyncRule).where(SyncRule.user_id == user.id))).scalars().all()
    )
    if existing_count >= limit:
        noun = "rule" if limit == 1 else "rules"
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Your plan allows up to {limit} {noun}. Upgrade to Pro for more.",
        )

    new_rule = SyncRule(
        user_id=user.id,
        name=payload.name,
        direction=payload.direction,
        conditions=payload.conditions,
        actions=payload.actions,
        rule_order=payload.rule_order,
        is_active=payload.is_active,
    )
    db.add(new_rule)
    await db.commit()

    return {"status": "success", "id": str(new_rule.id)}


@router.put("/{rule_id}")
async def update_rule(
    rule_id: UUID,
    payload: RuleCreate,
    user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_db),
) -> dict[str, Any]:
    """Update an existing sync rule."""
    _validate_direction(payload.direction)

    result = await db.execute(
        select(SyncRule).where(SyncRule.id == rule_id, SyncRule.user_id == user.id)
    )
    rule = result.scalar_one_or_none()
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rule not found.")

    rule.name = payload.name
    rule.direction = payload.direction
    rule.conditions = payload.conditions
    rule.actions = payload.actions
    rule.rule_order = payload.rule_order
    rule.is_active = payload.is_active
    await db.commit()

    return {"status": "success", "id": str(rule.id)}


@router.delete("/{rule_id}")
async def delete_rule(
    rule_id: UUID,
    user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_db),
) -> dict[str, str]:
    """Delete an existing sync rule."""
    result = await db.execute(
        select(SyncRule).where(SyncRule.id == rule_id, SyncRule.user_id == user.id)
    )
    rule = result.scalar_one_or_none()
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rule not found.")

    await db.delete(rule)
    await db.commit()
    return {"status": "success"}

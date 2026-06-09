from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from .models import ArtifactGrant, ProductArtifact, Subscription, User

PLAN_RANK = {"starter": 1, "pro": 2}
ACTIVE_STATUSES = {"trialing", "active"}


def _is_current(subscription: Subscription, now: datetime) -> bool:
    if subscription.status not in ACTIVE_STATUSES:
        return False
    if subscription.current_period_end is None:
        return True
    period_end = subscription.current_period_end
    if period_end.tzinfo is None:
        period_end = period_end.replace(tzinfo=timezone.utc)
    return period_end > now


def active_plan_code(db: Session, user_id: int) -> str | None:
    now = datetime.now(timezone.utc)
    subscriptions = (
        db.query(Subscription)
        .filter(Subscription.user_id == user_id)
        .order_by(Subscription.updated_at.desc(), Subscription.id.desc())
        .all()
    )
    valid = [item.plan_code for item in subscriptions if _is_current(item, now)]
    return max(valid, key=lambda code: PLAN_RANK.get(code, 0), default=None)


def has_plan(db: Session, user: User, minimum_plan: str) -> bool:
    if user.role == "admin":
        return True
    required_rank = PLAN_RANK.get(minimum_plan)
    if required_rank is None:
        return False
    active = active_plan_code(db, user.id)
    return PLAN_RANK.get(active or "", 0) >= required_rank


def has_artifact_access(db: Session, user: User, artifact: ProductArtifact) -> bool:
    if not artifact.is_active:
        return False
    if user.role == "admin":
        return True
    if artifact.required_plan in PLAN_RANK and has_plan(db, user, artifact.required_plan):
        return True
    grant = (
        db.query(ArtifactGrant)
        .filter(
            ArtifactGrant.user_id == user.id,
            ArtifactGrant.artifact_id == artifact.id,
            ArtifactGrant.status == "active",
        )
        .first()
    )
    return grant is not None


def require_plan(db: Session, user: User, minimum_plan: str) -> None:
    if not has_plan(db, user, minimum_plan):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"{minimum_plan} entitlement required",
        )


def require_artifact(db: Session, user: User, artifact: ProductArtifact) -> None:
    if not has_artifact_access(db, user, artifact):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="artifact entitlement required",
        )

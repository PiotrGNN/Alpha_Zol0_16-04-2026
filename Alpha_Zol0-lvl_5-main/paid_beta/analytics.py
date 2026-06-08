from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from .models import Plan, Subscription, UsageEvent

FUNNEL_EVENTS = (
    "landing_view",
    "signup_completed",
    "onboarding_completed",
    "first_report_generated",
    "checkout_started",
    "checkout_completed",
    "subscription_activated",
)


def record_event(
    db: Session,
    *,
    event_name: str,
    user_id: int | None,
    properties: dict | None = None,
    commit: bool = True,
) -> UsageEvent:
    event = UsageEvent(
        user_id=user_id,
        event_name=event_name,
        properties=json.dumps(properties or {}, sort_keys=True),
        created_at=datetime.now(timezone.utc),
    )
    db.add(event)
    if commit:
        db.commit()
        db.refresh(event)
    else:
        db.flush()
    return event


def funnel_summary(db: Session) -> dict[str, int]:
    rows = (
        db.query(UsageEvent.event_name, func.count(UsageEvent.id))
        .filter(UsageEvent.event_name.in_(FUNNEL_EVENTS))
        .group_by(UsageEvent.event_name)
        .all()
    )
    counts = {name: 0 for name in FUNNEL_EVENTS}
    counts.update({name: int(count) for name, count in rows})
    return counts


def mrr_summary(db: Session) -> dict[str, float | int]:
    active = (
        db.query(Subscription)
        .filter(Subscription.status.in_(("trialing", "active")))
        .all()
    )
    prices = {plan.code: float(plan.monthly_price or 0) for plan in db.query(Plan).all()}
    return {
        "active_subscriptions": len(active),
        "mrr": round(sum(prices.get(item.plan_code, 0.0) for item in active), 2),
    }

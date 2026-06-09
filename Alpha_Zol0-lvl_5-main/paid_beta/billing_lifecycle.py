from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import (
    ArtifactGrant,
    CheckoutSession,
    ProductArtifact,
    Subscription,
    User,
    WebhookEvent,
)


def purchasable_artifact(db: Session, slug: str | None) -> ProductArtifact:
    if not slug:
        raise HTTPException(status_code=400, detail="artifact_slug is required for report")
    artifact = (
        db.query(ProductArtifact)
        .filter(
            ProductArtifact.slug == slug,
            ProductArtifact.resource_type.in_(("report", "backtest")),
            ProductArtifact.required_plan == "one_time",
            ProductArtifact.is_active.is_(True),
        )
        .one_or_none()
    )
    if artifact is None:
        raise HTTPException(status_code=404, detail="purchasable artifact not found")
    return artifact


def subscription_from_payload(db: Session, payload: dict) -> Subscription | None:
    subscription_id = payload.get("subscription") or payload.get("id")
    if not subscription_id:
        return None
    return (
        db.query(Subscription)
        .filter(Subscription.provider_subscription_id == str(subscription_id))
        .one_or_none()
    )


def upsert_subscription(
    db: Session, payload: dict, *, status_override: str | None = None
) -> Subscription | None:
    metadata = payload.get("metadata") or {}
    subscription = subscription_from_payload(db, payload)
    user_id = metadata.get("user_id")
    if subscription is None:
        if not user_id:
            return None
        user = db.get(User, int(user_id))
        if user is None:
            return None
        subscription_id = payload.get("subscription") or payload.get("id")
        subscription = Subscription(
            user_id=user.id,
            plan_code=str(metadata.get("product_code") or "pro"),
            provider="stripe",
            provider_subscription_id=str(subscription_id),
        )
        db.add(subscription)
    else:
        user = db.get(User, subscription.user_id)
    customer_id = payload.get("customer")
    if user is not None and customer_id and not user.stripe_customer_id:
        user.stripe_customer_id = str(customer_id)
    if metadata.get("product_code") in {"starter", "pro"}:
        subscription.plan_code = str(metadata["product_code"])
    subscription.status = status_override or str(payload.get("status") or "incomplete")
    period_end = payload.get("current_period_end")
    if period_end:
        subscription.current_period_end = datetime.fromtimestamp(
            int(period_end), tz=timezone.utc
        )
    return subscription


def grant_report(db: Session, obj: dict, event_id: str) -> None:
    metadata = obj.get("metadata") or {}
    user_id = metadata.get("user_id")
    artifact_id = metadata.get("artifact_id")
    if not user_id or not artifact_id:
        return
    artifact = db.get(ProductArtifact, int(artifact_id))
    if artifact is None or not artifact.is_active or artifact.required_plan != "one_time":
        return
    checkout = (
        db.query(CheckoutSession)
        .filter(CheckoutSession.provider_session_id == str(obj.get("id")))
        .one_or_none()
    )
    if checkout is None or checkout.artifact_id != artifact.id:
        return
    checkout.status = "complete"
    checkout.payment_status = str(obj.get("payment_status") or "")
    if obj.get("payment_intent"):
        checkout.provider_payment_intent_id = str(obj["payment_intent"])
    if checkout.payment_status != "paid":
        return
    grant = (
        db.query(ArtifactGrant)
        .filter(
            ArtifactGrant.user_id == int(user_id),
            ArtifactGrant.artifact_id == artifact.id,
        )
        .one_or_none()
    )
    if grant is None:
        grant = ArtifactGrant(
            user_id=int(user_id),
            artifact_id=artifact.id,
            checkout_session_id=checkout.id,
        )
        db.add(grant)
    grant.status = "active"
    grant.provider_event_id = event_id
    grant.revoked_at = None


def checkout_from_payment(db: Session, obj: dict) -> CheckoutSession | None:
    payment_intent = obj.get("payment_intent")
    if payment_intent:
        return (
            db.query(CheckoutSession)
            .filter(CheckoutSession.provider_payment_intent_id == str(payment_intent))
            .one_or_none()
        )
    metadata = obj.get("metadata") or {}
    if not metadata.get("user_id") or not metadata.get("artifact_id"):
        return None
    return (
        db.query(CheckoutSession)
        .filter(
            CheckoutSession.user_id == int(metadata["user_id"]),
            CheckoutSession.artifact_id == int(metadata["artifact_id"]),
        )
        .order_by(CheckoutSession.id.desc())
        .first()
    )


def revoke_grant(
    db: Session,
    obj: dict,
    *,
    checkout_status: str,
    payment_status: str,
) -> None:
    checkout = checkout_from_payment(db, obj)
    if checkout is None or checkout.artifact_id is None:
        return
    checkout.status = checkout_status
    checkout.payment_status = payment_status
    db.query(ArtifactGrant).filter(
        ArtifactGrant.user_id == checkout.user_id,
        ArtifactGrant.artifact_id == checkout.artifact_id,
    ).update(
        {
            ArtifactGrant.status: "revoked",
            ArtifactGrant.revoked_at: datetime.now(timezone.utc),
        },
        synchronize_session=False,
    )


def store_event_once(db: Session, event: dict) -> WebhookEvent | None:
    stored = WebhookEvent(
        provider="stripe",
        provider_event_id=str(event["id"]),
        event_type=str(event["type"]),
        payload=json.dumps(event, default=str, sort_keys=True),
    )
    try:
        with db.begin_nested():
            db.add(stored)
            db.flush()
    except IntegrityError:
        return None
    return stored

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .analytics import record_event
from .audit import record_audit
from .config import settings
from .database import get_db
from .dependencies import require_user
from .models import (
    ArtifactGrant,
    CheckoutSession,
    ProductArtifact,
    Subscription,
    User,
    WebhookEvent,
)

router = APIRouter(prefix="/billing", tags=["billing"])


class CheckoutRequest(BaseModel):
    product_code: str
    artifact_slug: str | None = None


def _stripe():
    try:
        import stripe
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="stripe dependency is not installed",
        ) from exc
    stripe.api_key = settings.stripe_secret_key
    return stripe


def _price_for(product_code: str) -> tuple[str, str]:
    mapping = {
        "starter": (settings.stripe_price_starter, "subscription"),
        "pro": (settings.stripe_price_pro, "subscription"),
        "report": (settings.stripe_price_report, "payment"),
    }
    price_id, mode = mapping.get(product_code, ("", ""))
    if not price_id:
        raise HTTPException(status_code=400, detail="unknown or unconfigured product")
    return price_id, mode


def _report_artifact(db: Session, slug: str | None) -> ProductArtifact:
    if not slug:
        raise HTTPException(status_code=400, detail="artifact_slug is required for report")
    artifact = (
        db.query(ProductArtifact)
        .filter(
            ProductArtifact.slug == slug,
            ProductArtifact.resource_type.in_(("report", "backtest")),
            ProductArtifact.is_active.is_(True),
        )
        .one_or_none()
    )
    if artifact is None:
        raise HTTPException(status_code=404, detail="purchasable artifact not found")
    return artifact


@router.post("/checkout")
def create_checkout(
    request: CheckoutRequest,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    price_id, mode = _price_for(request.product_code)
    artifact = _report_artifact(db, request.artifact_slug) if request.product_code == "report" else None
    stripe = _stripe()
    metadata = {"user_id": str(user.id), "product_code": request.product_code}
    if artifact is not None:
        metadata.update({"artifact_id": str(artifact.id), "artifact_slug": artifact.slug})
    params = {
        "mode": mode,
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": f"{settings.app_url}/account/billing?checkout=success",
        "cancel_url": f"{settings.app_url}/pricing?checkout=cancelled",
        "metadata": metadata,
    }
    if mode == "subscription":
        params["subscription_data"] = {"metadata": metadata}
    if user.stripe_customer_id:
        params["customer"] = user.stripe_customer_id
    else:
        params["customer_email"] = user.email
    session = stripe.checkout.Session.create(**params)
    checkout = CheckoutSession(
        user_id=user.id,
        product_code=request.product_code,
        artifact_id=artifact.id if artifact else None,
        provider_session_id=session.id,
        mode=mode,
        status=getattr(session, "status", "open") or "open",
        payment_status=getattr(session, "payment_status", None),
    )
    db.add(checkout)
    db.flush()
    record_event(
        db,
        event_name="checkout_started",
        user_id=user.id,
        properties={"product_code": request.product_code, "artifact_slug": request.artifact_slug},
        commit=False,
    )
    record_audit(
        db,
        action="billing.checkout_started",
        user_id=user.id,
        resource_type=request.product_code,
        resource_id=artifact.slug if artifact else request.product_code,
    )
    db.commit()
    return {"checkout_url": session.url, "session_id": session.id}


@router.post("/portal")
def create_portal(user: User = Depends(require_user)):
    if not user.stripe_customer_id:
        raise HTTPException(status_code=409, detail="stripe customer is not linked")
    stripe = _stripe()
    session = stripe.billing_portal.Session.create(
        customer=user.stripe_customer_id,
        return_url=f"{settings.app_url}/account/billing",
    )
    return {"portal_url": session.url}


def _upsert_subscription(
    db: Session, payload: dict, *, status_override: str | None = None
) -> Subscription | None:
    metadata = payload.get("metadata") or {}
    user_id = metadata.get("user_id")
    subscription_id = payload.get("subscription") or payload.get("id")
    if not user_id or not subscription_id:
        return None
    user = db.get(User, int(user_id))
    if user is None:
        return None
    customer_id = payload.get("customer")
    if customer_id and not user.stripe_customer_id:
        user.stripe_customer_id = str(customer_id)
    subscription = (
        db.query(Subscription)
        .filter(Subscription.provider_subscription_id == str(subscription_id))
        .one_or_none()
    )
    if subscription is None:
        subscription = Subscription(
            user_id=user.id,
            plan_code=str(metadata.get("product_code") or "pro"),
            provider="stripe",
            provider_subscription_id=str(subscription_id),
        )
        db.add(subscription)
    subscription.status = status_override or str(payload.get("status") or "active")
    period_end = payload.get("current_period_end")
    if period_end:
        subscription.current_period_end = datetime.fromtimestamp(int(period_end), tz=timezone.utc)
    return subscription


def _grant_report(db: Session, obj: dict, event_id: str) -> None:
    metadata = obj.get("metadata") or {}
    user_id = metadata.get("user_id")
    artifact_id = metadata.get("artifact_id")
    if not user_id or not artifact_id:
        return
    checkout = (
        db.query(CheckoutSession)
        .filter(CheckoutSession.provider_session_id == str(obj.get("id")))
        .one_or_none()
    )
    if checkout is None:
        return
    checkout.status = "complete"
    checkout.payment_status = str(obj.get("payment_status") or "paid")
    if checkout.payment_status != "paid":
        return
    grant = (
        db.query(ArtifactGrant)
        .filter(
            ArtifactGrant.user_id == int(user_id),
            ArtifactGrant.artifact_id == int(artifact_id),
        )
        .one_or_none()
    )
    if grant is None:
        grant = ArtifactGrant(
            user_id=int(user_id),
            artifact_id=int(artifact_id),
            checkout_session_id=checkout.id,
        )
        db.add(grant)
    grant.status = "active"
    grant.provider_event_id = event_id
    grant.revoked_at = None


def _revoke_grant(db: Session, obj: dict) -> None:
    metadata = obj.get("metadata") or {}
    user_id = metadata.get("user_id")
    artifact_id = metadata.get("artifact_id")
    if not user_id or not artifact_id:
        return
    now = datetime.now(timezone.utc)
    db.query(ArtifactGrant).filter(
        ArtifactGrant.user_id == int(user_id),
        ArtifactGrant.artifact_id == int(artifact_id),
    ).update(
        {ArtifactGrant.status: "revoked", ArtifactGrant.revoked_at: now},
        synchronize_session=False,
    )


def _store_event_once(db: Session, event: dict) -> WebhookEvent | None:
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


@router.post("/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    stripe = _stripe()
    payload = await request.body()
    signature = request.headers.get("Stripe-Signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, signature, settings.stripe_webhook_secret)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid stripe webhook") from exc

    stored = _store_event_once(db, event)
    if stored is None:
        db.rollback()
        return {"ok": True, "duplicate": True}

    obj = event.get("data", {}).get("object", {})
    event_type = str(event["type"])
    event_id = str(event["id"])
    metadata = obj.get("metadata") or {}
    user_id = int(metadata["user_id"]) if metadata.get("user_id") else None

    if event_type in {"checkout.session.completed", "checkout.session.async_payment_succeeded"}:
        checkout = (
            db.query(CheckoutSession)
            .filter(CheckoutSession.provider_session_id == str(obj.get("id")))
            .one_or_none()
        )
        if checkout:
            checkout.status = "complete"
            checkout.payment_status = str(obj.get("payment_status") or "paid")
        if metadata.get("product_code") == "report":
            _grant_report(db, obj, event_id)
        elif obj.get("subscription"):
            _upsert_subscription(db, obj, status_override="active")
        if user_id:
            record_event(
                db,
                event_name="checkout_completed",
                user_id=user_id,
                properties={"product_code": metadata.get("product_code")},
                commit=False,
            )
    elif event_type in {"checkout.session.expired", "checkout.session.async_payment_failed"}:
        checkout = (
            db.query(CheckoutSession)
            .filter(CheckoutSession.provider_session_id == str(obj.get("id")))
            .one_or_none()
        )
        if checkout:
            checkout.status = "failed"
            checkout.payment_status = str(obj.get("payment_status") or "unpaid")
        _revoke_grant(db, obj)
    elif event_type.startswith("customer.subscription."):
        status_value = "canceled" if event_type.endswith("deleted") else None
        _upsert_subscription(db, obj, status_override=status_value)
        if user_id:
            record_event(
                db,
                event_name="subscription_canceled" if status_value else "subscription_activated",
                user_id=user_id,
                properties={"plan": metadata.get("product_code")},
                commit=False,
            )
    elif event_type == "invoice.payment_failed":
        subscription_id = obj.get("subscription")
        if subscription_id:
            db.query(Subscription).filter(
                Subscription.provider_subscription_id == str(subscription_id)
            ).update({Subscription.status: "past_due"}, synchronize_session=False)
        if user_id:
            record_event(db, event_name="payment_failed", user_id=user_id, properties={}, commit=False)
    elif event_type in {"charge.refunded", "refund.created"}:
        _revoke_grant(db, obj)

    record_audit(
        db,
        action="billing.webhook_processed",
        user_id=user_id,
        resource_type="stripe_event",
        resource_id=event_id,
        metadata={"event_type": event_type},
    )
    stored.processed = True
    stored.processed_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True, "duplicate": False}

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .analytics import record_event
from .audit import record_audit
from .billing_lifecycle import (
    grant_report,
    purchasable_artifact,
    revoke_grant,
    store_event_once,
    subscription_from_payload,
    upsert_subscription,
)
from .config import settings
from .database import get_db
from .dependencies import require_user
from .models import CheckoutSession, Subscription, User

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


@router.post("/checkout")
def create_checkout(
    request: CheckoutRequest,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    price_id, mode = _price_for(request.product_code)
    artifact = (
        purchasable_artifact(db, request.artifact_slug)
        if request.product_code == "report"
        else None
    )
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
        provider_payment_intent_id=getattr(session, "payment_intent", None),
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
        properties={
            "product_code": request.product_code,
            "artifact_slug": request.artifact_slug,
        },
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


@router.post("/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    stripe = _stripe()
    payload = await request.body()
    signature = request.headers.get("Stripe-Signature", "")
    try:
        event = stripe.Webhook.construct_event(
            payload, signature, settings.stripe_webhook_secret
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid stripe webhook") from exc

    stored = store_event_once(db, event)
    if stored is None:
        db.rollback()
        return {"ok": True, "duplicate": True}

    obj = event.get("data", {}).get("object", {})
    event_type = str(event["type"])
    event_id = str(event["id"])
    metadata = obj.get("metadata") or {}
    existing_subscription = subscription_from_payload(db, obj)
    user_id = (
        int(metadata["user_id"])
        if metadata.get("user_id")
        else (
            existing_subscription.user_id
            if existing_subscription is not None
            else None
        )
    )

    if event_type in {
        "checkout.session.completed",
        "checkout.session.async_payment_succeeded",
    }:
        checkout = (
            db.query(CheckoutSession)
            .filter(CheckoutSession.provider_session_id == str(obj.get("id")))
            .one_or_none()
        )
        if checkout:
            checkout.status = "complete"
            checkout.payment_status = str(obj.get("payment_status") or "")
            if obj.get("payment_intent"):
                checkout.provider_payment_intent_id = str(obj["payment_intent"])
        if metadata.get("product_code") == "report":
            grant_report(db, obj, event_id)
        elif obj.get("subscription"):
            upsert_subscription(db, obj, status_override="active")
        if user_id:
            record_event(
                db,
                event_name="checkout_completed",
                user_id=user_id,
                properties={"product_code": metadata.get("product_code")},
                commit=False,
            )
    elif event_type in {
        "checkout.session.expired",
        "checkout.session.async_payment_failed",
    }:
        revoke_grant(
            db,
            obj,
            checkout_status="failed",
            payment_status=str(obj.get("payment_status") or "unpaid"),
        )
    elif event_type.startswith("customer.subscription."):
        status_value = "canceled" if event_type.endswith("deleted") else None
        updated = upsert_subscription(db, obj, status_override=status_value)
        if updated is not None and user_id:
            record_event(
                db,
                event_name=(
                    "subscription_canceled"
                    if status_value
                    else "subscription_activated"
                ),
                user_id=user_id,
                properties={"plan": updated.plan_code},
                commit=False,
            )
    elif event_type == "invoice.payment_failed":
        subscription_id = obj.get("subscription")
        if subscription_id:
            db.query(Subscription).filter(
                Subscription.provider_subscription_id == str(subscription_id)
            ).update(
                {Subscription.status: "past_due"}, synchronize_session=False
            )
        if user_id:
            record_event(
                db,
                event_name="payment_failed",
                user_id=user_id,
                properties={},
                commit=False,
            )
    elif event_type in {"charge.refunded", "refund.created"}:
        revoke_grant(
            db,
            obj,
            checkout_status="refunded",
            payment_status="refunded",
        )

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

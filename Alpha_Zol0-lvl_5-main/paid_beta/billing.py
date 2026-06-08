from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .analytics import record_event
from .config import settings
from .database import get_db
from .dependencies import require_user
from .models import CheckoutSession, Subscription, User, WebhookEvent

router = APIRouter(prefix="/billing", tags=["billing"])


class CheckoutRequest(BaseModel):
    product_code: str


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
    stripe = _stripe()
    metadata = {"user_id": str(user.id), "product_code": request.product_code}
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
    db.add(
        CheckoutSession(
            user_id=user.id,
            product_code=request.product_code,
            provider_session_id=session.id,
            mode=mode,
            status=getattr(session, "status", "open") or "open",
        )
    )
    db.commit()
    record_event(
        db,
        event_name="checkout_started",
        user_id=user.id,
        properties={"product_code": request.product_code},
    )
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
) -> None:
    metadata = payload.get("metadata") or {}
    user_id = metadata.get("user_id")
    subscription_id = payload.get("subscription") or payload.get("id")
    if not user_id or not subscription_id:
        return
    user = db.get(User, int(user_id))
    if user is None:
        return
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
        subscription.current_period_end = datetime.fromtimestamp(
            int(period_end), tz=timezone.utc
        )


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

    event_id = str(event["id"])
    if (
        db.query(WebhookEvent)
        .filter(WebhookEvent.provider_event_id == event_id)
        .first()
    ):
        return {"ok": True, "duplicate": True}

    stored = WebhookEvent(
        provider="stripe",
        provider_event_id=event_id,
        event_type=str(event["type"]),
        payload=json.dumps(event, default=str, sort_keys=True),
    )
    db.add(stored)
    db.flush()

    obj = event.get("data", {}).get("object", {})
    event_type = str(event["type"])
    if event_type == "checkout.session.completed":
        metadata = obj.get("metadata") or {}
        user_id = metadata.get("user_id")
        checkout = (
            db.query(CheckoutSession)
            .filter(CheckoutSession.provider_session_id == str(obj.get("id")))
            .one_or_none()
        )
        if checkout:
            checkout.status = "complete"
        if user_id:
            record_event(
                db,
                event_name="checkout_completed",
                user_id=int(user_id),
                properties={"product_code": metadata.get("product_code")},
                commit=False,
            )
        if obj.get("subscription"):
            _upsert_subscription(db, obj, status_override="active")
    elif event_type.startswith("customer.subscription."):
        status_value = "canceled" if event_type.endswith("deleted") else None
        _upsert_subscription(db, obj, status_override=status_value)
        metadata = obj.get("metadata") or {}
        if metadata.get("user_id"):
            event_name = (
                "subscription_canceled"
                if status_value == "canceled"
                else "subscription_activated"
            )
            record_event(
                db,
                event_name=event_name,
                user_id=int(metadata["user_id"]),
                properties={"plan": metadata.get("product_code")},
                commit=False,
            )
    elif event_type == "invoice.payment_failed":
        metadata = obj.get("metadata") or {}
        if metadata.get("user_id"):
            record_event(
                db,
                event_name="payment_failed",
                user_id=int(metadata["user_id"]),
                properties={},
                commit=False,
            )

    stored.processed = True
    stored.processed_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True, "duplicate": False}

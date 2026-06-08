from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .analytics import FUNNEL_EVENTS, funnel_summary, mrr_summary, record_event
from .billing import router as billing_router
from .config import settings
from .database import get_db, init_db
from .dependencies import require_admin, require_user
from .models import Plan, Subscription, UsageEvent, User
from .security import create_token, hash_password, verify_password


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.validate_runtime()
    init_db()
    from .database import SessionLocal

    db = SessionLocal()
    try:
        defaults = (
            ("starter", "Starter", "subscription", 29.0, settings.stripe_price_starter),
            ("pro", "Pro", "subscription", 79.0, settings.stripe_price_pro),
            ("report", "Single report", "one_time", 0.0, settings.stripe_price_report),
        )
        for code, name, kind, price, provider_price_id in defaults:
            plan = db.query(Plan).filter(Plan.code == code).one_or_none()
            if plan is None:
                db.add(
                    Plan(
                        code=code,
                        name=name,
                        billing_kind=kind,
                        monthly_price=price,
                        provider_price_id=provider_price_id,
                    )
                )
        db.commit()
    finally:
        db.close()
    yield


app = FastAPI(title="ZoL0 Paid Beta API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Stripe-Signature"],
)

public = APIRouter(tags=["public"])
auth = APIRouter(prefix="/auth", tags=["auth"])
internal = APIRouter(prefix="/internal", tags=["internal"])


class Credentials(BaseModel):
    email: EmailStr
    password: str


class EventRequest(BaseModel):
    event_name: str
    properties: dict = Field(default_factory=dict)


@public.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "paid-beta-api",
        "public_live_trading": False,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@public.get("/status")
def status_endpoint(db: Session = Depends(get_db)) -> dict:
    db.execute(text("SELECT 1"))
    return {"status": "ready", "database": "ok", "public_live_trading": False}


@auth.post("/register", status_code=201)
def register(credentials: Credentials, db: Session = Depends(get_db)):
    email = credentials.email.lower()
    user = User(
        email=email,
        password_hash=hash_password(credentials.password),
        role="user",
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="email already registered") from exc
    db.refresh(user)
    record_event(db, event_name="signup_completed", user_id=user.id, properties={})
    token = create_token(
        user_id=user.id,
        role=user.role,
        secret=settings.token_secret,
        ttl_seconds=settings.token_ttl_seconds,
    )
    return {"access_token": token, "token_type": "bearer", "role": user.role}


@auth.post("/login")
def login(credentials: Credentials, db: Session = Depends(get_db)):
    user = (
        db.query(User)
        .filter(User.email == credentials.email.lower())
        .one_or_none()
    )
    if user is None or not verify_password(credentials.password, user.password_hash):
        raise HTTPException(status_code=401, detail="invalid credentials")
    token = create_token(
        user_id=user.id,
        role=user.role,
        secret=settings.token_secret,
        ttl_seconds=settings.token_ttl_seconds,
    )
    return {"access_token": token, "token_type": "bearer", "role": user.role}


@auth.get("/me")
def me(user: User = Depends(require_user), db: Session = Depends(get_db)):
    active_plan = (
        db.query(Subscription.plan_code)
        .filter(
            Subscription.user_id == user.id,
            Subscription.status.in_(("trialing", "active")),
        )
        .first()
    )
    return {
        "id": user.id,
        "email": user.email,
        "role": user.role,
        "active_plan": active_plan[0] if active_plan else None,
    }


@app.post("/events", status_code=202)
def create_event(
    request: EventRequest,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    allowed = set(FUNNEL_EVENTS) | {"subscription_canceled", "payment_failed"}
    if request.event_name not in allowed:
        raise HTTPException(status_code=400, detail="unsupported event")
    event = record_event(
        db,
        event_name=request.event_name,
        user_id=user.id,
        properties=request.properties,
    )
    return {"accepted": True, "event_id": event.id}


@internal.get("/funnel")
def admin_funnel(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return funnel_summary(db)


@internal.get("/mrr")
def admin_mrr(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return mrr_summary(db)


@internal.get("/runtime-health")
def runtime_health(
    _: User = Depends(require_admin), db: Session = Depends(get_db)
):
    last_event = db.query(UsageEvent).order_by(UsageEvent.created_at.desc()).first()
    return {
        "api": "ok",
        "database": "ok",
        "last_product_event_at": (
            last_event.created_at.isoformat() if last_event else None
        ),
        "public_live_trading": False,
    }


app.include_router(public)
app.include_router(auth)
app.include_router(billing_router)
app.include_router(internal)

from __future__ import annotations

import hmac
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .analytics import FUNNEL_EVENTS, funnel_summary, mrr_summary, record_event
from .audit import record_audit
from .billing import router as billing_router
from .config import settings
from .database import get_db, init_db
from .dependencies import require_admin, require_user
from .entitlements import active_plan_code
from .middleware import SecurityAndMetricsMiddleware, metrics_snapshot
from .models import Plan, ProductArtifact, UsageEvent, User
from .password_reset import router as password_reset_router
from .resources import router as resources_router
from .security import create_token, hash_password, verify_password
from .session import router as session_router


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
        artifact_defaults = (
            (
                "paper-market-weekly",
                "PAPER Market Weekly",
                "report",
                "starter",
                "Weekly KuCoin PAPER market summary.",
                {"scope": "KuCoin PAPER", "profitability_claim": False},
            ),
            (
                "strategy-backtest-evidence",
                "Strategy Backtest Evidence",
                "backtest",
                "pro",
                "Full-cost backtest evidence and limitations.",
                {"scope": "research", "live_ready": False},
            ),
            (
                "single-research-report",
                "Single Research Report",
                "report",
                "one_time",
                "Individually purchasable immutable research artifact.",
                {"scope": "research", "investment_advice": False},
            ),
        )
        for slug, title, resource_type, required_plan, summary, content in artifact_defaults:
            if db.query(ProductArtifact).filter(ProductArtifact.slug == slug).one_or_none() is None:
                db.add(
                    ProductArtifact(
                        slug=slug,
                        title=title,
                        resource_type=resource_type,
                        required_plan=required_plan,
                        summary=summary,
                        content=json.dumps(content, sort_keys=True),
                    )
                )
        db.commit()
    finally:
        db.close()
    yield


app = FastAPI(title="ZoL0 Paid Beta API", version="0.2.0", lifespan=lifespan)
app.add_middleware(SecurityAndMetricsMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "Stripe-Signature",
        "X-Admin-Bootstrap-Token",
    ],
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


def _token_for(user: User) -> str:
    return create_token(
        user_id=user.id,
        role=user.role,
        secret=settings.token_secret,
        ttl_seconds=settings.token_ttl_seconds,
        token_version=int(user.token_version or 0),
    )


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
    user = User(
        email=credentials.email.lower(),
        password_hash=hash_password(credentials.password),
        role="user",
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="email already registered") from exc
    record_event(db, event_name="signup_completed", user_id=user.id, properties={}, commit=False)
    record_audit(db, action="auth.register", user_id=user.id)
    db.commit()
    db.refresh(user)
    return {
        "access_token": _token_for(user),
        "token_type": "bearer",
        "role": user.role,
        "expires_in": settings.token_ttl_seconds,
    }


@auth.post("/login")
def login(credentials: Credentials, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == credentials.email.lower()).one_or_none()
    if user is None or not verify_password(credentials.password, user.password_hash):
        raise HTTPException(status_code=401, detail="invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=401, detail="inactive user")
    record_audit(db, action="auth.login", user_id=user.id)
    db.commit()
    return {
        "access_token": _token_for(user),
        "token_type": "bearer",
        "role": user.role,
        "expires_in": settings.token_ttl_seconds,
    }


@auth.get("/me")
def me(user: User = Depends(require_user), db: Session = Depends(get_db)):
    return {
        "id": user.id,
        "email": user.email,
        "role": user.role,
        "active_plan": active_plan_code(db, user.id),
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


@internal.post("/bootstrap-admin", status_code=201)
def bootstrap_admin(
    credentials: Credentials,
    bootstrap_token: str = Header(alias="X-Admin-Bootstrap-Token"),
    db: Session = Depends(get_db),
):
    if not settings.allow_admin_bootstrap:
        raise HTTPException(status_code=404, detail="not found")
    configured_token = settings.bootstrap_admin_secret
    if len(configured_token) < 32:
        raise HTTPException(status_code=503, detail="admin bootstrap is not configured")
    if not hmac.compare_digest(bootstrap_token, configured_token):
        raise HTTPException(status_code=403, detail="invalid admin bootstrap token")
    if db.query(User).filter(User.role == "admin").first() is not None:
        raise HTTPException(status_code=409, detail="admin bootstrap already completed")
    email = credentials.email.lower()
    if settings.bootstrap_admin_email and email != settings.bootstrap_admin_email:
        raise HTTPException(status_code=403, detail="admin email is not authorized")
    if db.query(User).filter(User.email == email).first() is not None:
        raise HTTPException(status_code=409, detail="admin email is already registered")
    user = User(email=email, password_hash=hash_password(credentials.password), role="admin")
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="admin bootstrap failed") from exc
    record_audit(db, action="admin.bootstrap", user_id=user.id)
    db.commit()
    return {"created": True, "email": user.email, "role": user.role}


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
        "metrics": metrics_snapshot(),
        "last_product_event_at": last_event.created_at.isoformat() if last_event else None,
        "public_live_trading": False,
    }


app.include_router(public)
app.include_router(auth)
app.include_router(session_router)
app.include_router(password_reset_router)
app.include_router(billing_router)
app.include_router(resources_router)
app.include_router(internal)

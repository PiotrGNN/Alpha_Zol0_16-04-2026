from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .audit import record_audit
from .business_metrics import build_business_metrics
from .config import settings
from .database import get_db
from .dependencies import require_admin
from .economics_models import EconomicsPeriod
from .models import User
from .trading_metrics import assess_trading_metrics, load_scorecard

router = APIRouter(prefix="/admin", tags=["internal"])
PROJECT_DIR = Path(__file__).resolve().parents[1]


class EconomicsPeriodRequest(BaseModel):
    period_start: date
    period_end: date
    source: str = Field(min_length=2, max_length=64)
    currency: str = Field(default="PLN", min_length=3, max_length=3)
    gross_revenue: float = Field(ge=0)
    payment_fees: float = Field(default=0, ge=0)
    refunds: float = Field(default=0, ge=0)
    hosting_cost: float = Field(default=0, ge=0)
    support_cost: float = Field(default=0, ge=0)
    acquisition_spend: float = Field(default=0, ge=0)
    other_variable_cost: float = Field(default=0, ge=0)
    active_customers: int = Field(default=0, ge=0)
    new_customers: int = Field(default=0, ge=0)
    churned_customers: int = Field(default=0, ge=0)
    activated_customers: int = Field(default=0, ge=0)
    checkout_started: int = Field(default=0, ge=0)
    checkout_completed: int = Field(default=0, ge=0)
    failed_payments: int = Field(default=0, ge=0)
    recovered_payments: int = Field(default=0, ge=0)
    support_minutes: int = Field(default=0, ge=0)
    notes: str = Field(default="", max_length=4000)


@router.post("/economics-periods", status_code=201)
def create_economics_period(
    request: EconomicsPeriodRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if (request.period_end - request.period_start).days != 6:
        raise HTTPException(status_code=400, detail="economics period must contain exactly 7 days")
    if request.checkout_completed > request.checkout_started:
        raise HTTPException(status_code=400, detail="checkout_completed exceeds checkout_started")
    if request.activated_customers > request.new_customers:
        raise HTTPException(status_code=400, detail="activated_customers exceeds new_customers")
    if request.recovered_payments > request.failed_payments:
        raise HTTPException(status_code=400, detail="recovered_payments exceeds failed_payments")

    period = EconomicsPeriod(**request.model_dump())
    period.currency = request.currency.upper()
    db.add(period)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="economics period already exists") from exc
    record_audit(
        db,
        action="economics.period_recorded",
        user_id=admin.id,
        resource_type="economics_period",
        resource_id=period.id,
        metadata={
            "period_start": request.period_start.isoformat(),
            "period_end": request.period_end.isoformat(),
            "source": request.source,
        },
    )
    db.commit()
    db.refresh(period)
    return {"id": period.id, "recorded": True}


@router.get("/profitability-readiness")
def profitability_readiness(
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    scorecard_path = Path(settings.trading_scorecard_path)
    if not scorecard_path.is_absolute():
        scorecard_path = PROJECT_DIR / scorecard_path
    business = build_business_metrics(db)
    trading = assess_trading_metrics(load_scorecard(scorecard_path))
    legal = {
        "terms_approved": settings.terms_approved,
        "privacy_approved": settings.privacy_approved,
        "refunds_approved": settings.refunds_approved,
        "risk_disclosure_approved": settings.risk_disclosure_approved,
        "all_approved": settings.legal_approved,
    }
    revenue_blockers = list(business["closed_beta_blockers"])
    if not legal["all_approved"]:
        revenue_blockers.append("LEGAL_APPROVALS_INCOMPLETE")
    return {
        "revenue_ready": not revenue_blockers,
        "revenue_blockers": sorted(set(revenue_blockers)),
        "scale_ready": business["scale_ready"] and legal["all_approved"],
        "business": business,
        "legal": legal,
        "trading": trading,
        "live_ready": False,
        "profitability_claim_allowed": bool(
            business["closed_beta_ready"] and trading["profitability_ready"]
        ),
        "policy": "SaaS revenue, trading profitability and LIVE readiness are independent states",
    }

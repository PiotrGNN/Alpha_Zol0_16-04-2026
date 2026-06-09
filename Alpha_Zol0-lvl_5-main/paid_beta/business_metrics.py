from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from .economics_models import EconomicsPeriod

WEEKS_REQUIRED = 4


def _ratio(numerator: float, denominator: float) -> float | None:
    return None if denominator <= 0 else numerator / denominator


def _period_metrics(period: EconomicsPeriod) -> dict[str, Any]:
    revenue = float(period.gross_revenue or 0)
    variable_cost = sum(
        float(value or 0)
        for value in (
            period.payment_fees,
            period.refunds,
            period.hosting_cost,
            period.support_cost,
            period.other_variable_cost,
        )
    )
    contribution = revenue - variable_cost
    acquisition = float(period.acquisition_spend or 0)
    active = int(period.active_customers or 0)
    new = int(period.new_customers or 0)
    churned = int(period.churned_customers or 0)
    weekly_per_customer = _ratio(contribution, active)
    monthly_per_customer = weekly_per_customer * 4.345 if weekly_per_customer is not None else None
    cac = _ratio(acquisition, new)
    payback = cac / monthly_per_customer if cac is not None and monthly_per_customer and monthly_per_customer > 0 else None
    churn = _ratio(churned, active + churned)
    monthly_churn = 1 - ((1 - churn) ** 4.345) if churn is not None and 0 < churn < 1 else churn
    implied_ltv = monthly_per_customer / monthly_churn if monthly_per_customer is not None and monthly_churn and monthly_churn > 0 else None
    ltv_cac = implied_ltv / cac if implied_ltv is not None and cac and cac > 0 else None
    return {
        "period_start": period.period_start.isoformat(),
        "period_end": period.period_end.isoformat(),
        "currency": period.currency,
        "gross_revenue": round(revenue, 2),
        "contribution": round(contribution, 2),
        "net_after_acquisition": round(contribution - acquisition, 2),
        "checkout_completion": _ratio(period.checkout_completed, period.checkout_started),
        "activation_rate": _ratio(period.activated_customers, new),
        "churn_rate": churn,
        "refund_rate": _ratio(float(period.refunds or 0), revenue),
        "gross_margin": _ratio(contribution, revenue),
        "payment_recovery": _ratio(period.recovered_payments, period.failed_payments),
        "support_minutes_per_customer": _ratio(period.support_minutes, active),
        "cac": cac,
        "cac_payback_months": payback,
        "ltv_cac": ltv_cac,
    }


def build_business_metrics(db: Session) -> dict[str, Any]:
    rows = db.query(EconomicsPeriod).order_by(EconomicsPeriod.period_start.desc()).limit(4).all()
    rows.reverse()
    metrics = [_period_metrics(row) for row in rows]
    return {"period_count": len(metrics), "periods": metrics, "ready": False, "blockers": ["THRESHOLDS_NOT_EVALUATED"]}

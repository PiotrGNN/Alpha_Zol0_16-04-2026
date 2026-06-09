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
    weekly_churn = _ratio(churned, active + churned)
    monthly_churn = 1 - ((1 - weekly_churn) ** 4.345) if weekly_churn is not None and 0 < weekly_churn < 1 else weekly_churn
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
        "churn_rate": weekly_churn,
        "monthly_churn_rate": monthly_churn,
        "refund_rate": _ratio(float(period.refunds or 0), revenue),
        "gross_margin": _ratio(contribution, revenue),
        "payment_recovery": _ratio(period.recovered_payments, period.failed_payments),
        "support_minutes_per_customer": _ratio(period.support_minutes, active),
        "cac": cac,
        "cac_payback_months": payback,
        "ltv_cac": ltv_cac,
    }


def _consecutive(metrics: list[dict[str, Any]]) -> bool:
    if len(metrics) != WEEKS_REQUIRED:
        return False
    starts = [date.fromisoformat(item["period_start"]) for item in metrics]
    ends = [date.fromisoformat(item["period_end"]) for item in metrics]
    if any((end - start).days != 6 for start, end in zip(starts, ends)):
        return False
    return all(starts[index] == ends[index - 1] + timedelta(days=1) for index in range(1, len(starts)))


def _evaluate_period(item: dict[str, Any], *, scale: bool) -> list[str]:
    reasons: list[str] = []
    minimums = {
        "checkout_completion": 0.70 if scale else 0.60,
        "activation_rate": 0.65 if scale else 0.50,
        "gross_margin": 0.75 if scale else 0.65,
    }
    maximums = {
        "churn_rate": 0.01174 if scale else 0.02396,
        "support_minutes_per_customer": 15.0 if scale else 30.0,
    }
    for field, threshold in minimums.items():
        value = item.get(field)
        if value is None:
            reasons.append(f"{field.upper()}_MISSING")
        elif value < threshold:
            reasons.append(f"{field.upper()}_BELOW_THRESHOLD")
    for field, threshold in maximums.items():
        value = item.get(field)
        if value is None:
            reasons.append(f"{field.upper()}_MISSING")
        elif value > threshold:
            reasons.append(f"{field.upper()}_ABOVE_THRESHOLD")
    refund_rate = item.get("refund_rate")
    if refund_rate is None:
        reasons.append("REFUND_RATE_MISSING")
    elif refund_rate >= (0.04 if scale else 0.08):
        reasons.append("REFUND_RATE_NOT_BELOW_THRESHOLD")
    recovery = item.get("payment_recovery")
    if recovery is not None and recovery < (0.60 if scale else 0.40):
        reasons.append("PAYMENT_RECOVERY_BELOW_THRESHOLD")
    if item["contribution"] <= 0:
        reasons.append("CONTRIBUTION_NOT_POSITIVE")
    if item["net_after_acquisition"] <= 0:
        reasons.append("NET_AFTER_ACQUISITION_NOT_POSITIVE")
    if scale:
        cac = item.get("cac")
        payback = item.get("cac_payback_months")
        ltv_cac = item.get("ltv_cac")
        if cac is None:
            reasons.append("CAC_MISSING")
        elif cac > 0:
            if payback is None:
                reasons.append("CAC_PAYBACK_MISSING")
            elif payback > 3.0:
                reasons.append("CAC_PAYBACK_ABOVE_3_MONTHS")
            if ltv_cac is None:
                reasons.append("LTV_CAC_MISSING")
            elif ltv_cac < 3.0:
                reasons.append("LTV_CAC_BELOW_3")
    return reasons


def build_business_metrics(db: Session) -> dict[str, Any]:
    rows = db.query(EconomicsPeriod).order_by(EconomicsPeriod.period_start.desc()).limit(4).all()
    rows.reverse()
    metrics = [_period_metrics(row) for row in rows]
    shared: list[str] = []
    if len(metrics) < WEEKS_REQUIRED:
        shared.append("FOUR_WEEK_HISTORY_MISSING")
    if metrics and len({item["currency"] for item in metrics}) != 1:
        shared.append("MIXED_CURRENCY_PERIODS")
    if not _consecutive(metrics):
        shared.append("PERIODS_NOT_FOUR_CONSECUTIVE_WEEKS")
    closed_blockers = sorted(set(shared + [reason for item in metrics for reason in _evaluate_period(item, scale=False)]))
    scale_blockers = sorted(set(shared + [reason for item in metrics for reason in _evaluate_period(item, scale=True)]))
    return {
        "period_count": len(metrics),
        "periods": metrics,
        "closed_beta_ready": not closed_blockers,
        "scale_ready": not scale_blockers,
        "closed_beta_blockers": closed_blockers,
        "scale_blockers": scale_blockers,
        "method": {
            "required_consecutive_weeks": WEEKS_REQUIRED,
            "churn_rate": "weekly equivalent of monthly threshold",
            "churn_denominator": "active_customers + churned_customers",
            "ltv": "implied from monthly contribution per customer and monthlyized churn",
            "organic_acquisition": "zero acquisition spend does not require CAC payback or LTV/CAC",
        },
    }

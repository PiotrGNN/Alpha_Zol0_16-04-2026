from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from .economics_models import EconomicsPeriod

WEEKS_REQUIRED = 4


def _ratio(numerator: float, denominator: float) -> float | None:
    return None if denominator <= 0 else numerator / denominator


def build_business_metrics(db: Session) -> dict[str, Any]:
    rows = db.query(EconomicsPeriod).order_by(EconomicsPeriod.period_start.desc()).limit(4).all()
    return {"period_count": len(rows), "ready": False, "blockers": ["METRICS_NOT_EVALUATED"]}

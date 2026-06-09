from datetime import date, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from paid_beta.business_metrics import build_business_metrics
from paid_beta.database import Base
from paid_beta.economics_models import EconomicsPeriod


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _add_week(db, start: date, **overrides):
    values = {
        "period_start": start,
        "period_end": start + timedelta(days=6),
        "source": start.isoformat(),
        "currency": "PLN",
        "gross_revenue": 1000,
        "payment_fees": 25,
        "refunds": 10,
        "hosting_cost": 40,
        "support_cost": 30,
        "acquisition_spend": 0,
        "other_variable_cost": 20,
        "active_customers": 25,
        "new_customers": 5,
        "churned_customers": 0,
        "activated_customers": 4,
        "checkout_started": 10,
        "checkout_completed": 8,
        "failed_payments": 2,
        "recovered_payments": 2,
        "support_minutes": 250,
    }
    values.update(overrides)
    db.add(EconomicsPeriod(**values))
    db.commit()


def test_four_good_weeks_pass_closed_beta_and_scale():
    db = _session()
    start = date(2026, 5, 4)
    for index in range(4):
        _add_week(db, start + timedelta(days=7 * index))

    report = build_business_metrics(db)

    assert report["closed_beta_ready"] is True
    assert report["scale_ready"] is True
    assert report["closed_beta_blockers"] == []
    assert report["scale_blockers"] == []
    assert len(report["periods"]) == 4


def test_weak_economics_remain_blocked():
    db = _session()
    start = date(2026, 5, 4)
    for index in range(4):
        _add_week(
            db,
            start + timedelta(days=7 * index),
            gross_revenue=100,
            hosting_cost=150,
            acquisition_spend=200,
            checkout_completed=2,
            activated_customers=1,
            refunds=20,
        )

    report = build_business_metrics(db)

    assert report["closed_beta_ready"] is False
    assert report["scale_ready"] is False
    assert "CONTRIBUTION_NOT_POSITIVE" in report["closed_beta_blockers"]
    assert "NET_AFTER_ACQUISITION_NOT_POSITIVE" in report["scale_blockers"]


def test_non_consecutive_weeks_are_rejected():
    db = _session()
    starts = [
        date(2026, 5, 4),
        date(2026, 5, 11),
        date(2026, 5, 25),
        date(2026, 6, 1),
    ]
    for start in starts:
        _add_week(db, start)

    report = build_business_metrics(db)

    assert report["closed_beta_ready"] is False
    assert "PERIODS_NOT_FOUR_CONSECUTIVE_WEEKS" in report["closed_beta_blockers"]

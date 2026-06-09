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
        "acquisition_spend": 50,
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

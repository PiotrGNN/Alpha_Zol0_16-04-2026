from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, Date, DateTime, Integer, Numeric, String, Text, UniqueConstraint

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EconomicsPeriod(Base):
    __tablename__ = "paid_beta_economics_periods"
    __table_args__ = (
        UniqueConstraint(
            "period_start",
            "period_end",
            "source",
            name="uq_paid_beta_economics_period_source",
        ),
    )

    id = Column(Integer, primary_key=True)
    period_start = Column(Date, nullable=False, index=True)
    period_end = Column(Date, nullable=False, index=True)
    source = Column(String(64), nullable=False)
    currency = Column(String(3), nullable=False, default="PLN")
    gross_revenue = Column(Numeric(14, 2), nullable=False, default=0)
    payment_fees = Column(Numeric(14, 2), nullable=False, default=0)
    refunds = Column(Numeric(14, 2), nullable=False, default=0)
    hosting_cost = Column(Numeric(14, 2), nullable=False, default=0)
    support_cost = Column(Numeric(14, 2), nullable=False, default=0)
    acquisition_spend = Column(Numeric(14, 2), nullable=False, default=0)
    other_variable_cost = Column(Numeric(14, 2), nullable=False, default=0)
    active_customers = Column(Integer, nullable=False, default=0)
    new_customers = Column(Integer, nullable=False, default=0)
    churned_customers = Column(Integer, nullable=False, default=0)
    activated_customers = Column(Integer, nullable=False, default=0)
    checkout_started = Column(Integer, nullable=False, default=0)
    checkout_completed = Column(Integer, nullable=False, default=0)
    failed_payments = Column(Integer, nullable=False, default=0)
    recovered_payments = Column(Integer, nullable=False, default=0)
    support_minutes = Column(Integer, nullable=False, default=0)
    notes = Column(Text, nullable=False, default="")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

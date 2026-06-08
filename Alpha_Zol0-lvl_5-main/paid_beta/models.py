from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "paid_beta_users"

    id = Column(Integer, primary_key=True)
    email = Column(String(320), unique=True, index=True, nullable=False)
    password_hash = Column(String(512), nullable=False)
    role = Column(String(32), nullable=False, default="user")
    stripe_customer_id = Column(String(128), unique=True, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    subscriptions = relationship("Subscription", back_populates="user")


class Plan(Base):
    __tablename__ = "paid_beta_plans"

    id = Column(Integer, primary_key=True)
    code = Column(String(32), unique=True, index=True, nullable=False)
    name = Column(String(128), nullable=False)
    billing_kind = Column(String(32), nullable=False)
    monthly_price = Column(Numeric(12, 2), nullable=True)
    provider_price_id = Column(String(128), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)


class Subscription(Base):
    __tablename__ = "paid_beta_subscriptions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("paid_beta_users.id"), nullable=False, index=True)
    plan_code = Column(String(32), nullable=False, index=True)
    provider = Column(String(32), nullable=False, default="stripe")
    provider_subscription_id = Column(String(128), unique=True, nullable=True)
    status = Column(String(32), nullable=False, default="incomplete")
    current_period_end = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    user = relationship("User", back_populates="subscriptions")


class CheckoutSession(Base):
    __tablename__ = "paid_beta_checkout_sessions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("paid_beta_users.id"), nullable=False, index=True)
    product_code = Column(String(32), nullable=False)
    provider_session_id = Column(String(128), unique=True, nullable=False)
    mode = Column(String(32), nullable=False)
    status = Column(String(32), nullable=False, default="open")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class WebhookEvent(Base):
    __tablename__ = "paid_beta_webhook_events"

    id = Column(Integer, primary_key=True)
    provider = Column(String(32), nullable=False)
    provider_event_id = Column(String(128), unique=True, index=True, nullable=False)
    event_type = Column(String(128), nullable=False)
    payload = Column(Text, nullable=False)
    processed = Column(Boolean, nullable=False, default=False)
    processed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class UsageEvent(Base):
    __tablename__ = "paid_beta_usage_events"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("paid_beta_users.id"), nullable=True, index=True)
    event_name = Column(String(64), nullable=False, index=True)
    properties = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, index=True)

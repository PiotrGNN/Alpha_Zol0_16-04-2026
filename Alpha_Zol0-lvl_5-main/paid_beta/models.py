from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
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
    token_version = Column(Integer, nullable=False, default=0)
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


class ProductArtifact(Base):
    __tablename__ = "paid_beta_artifacts"

    id = Column(Integer, primary_key=True)
    slug = Column(String(160), unique=True, index=True, nullable=False)
    title = Column(String(240), nullable=False)
    resource_type = Column(String(32), nullable=False, index=True)
    required_plan = Column(String(32), nullable=False, default="starter")
    summary = Column(Text, nullable=False, default="")
    content = Column(Text, nullable=False, default="{}")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class ArtifactGrant(Base):
    __tablename__ = "paid_beta_artifact_grants"
    __table_args__ = (
        UniqueConstraint("user_id", "artifact_id", name="uq_paid_beta_grant_user_artifact"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("paid_beta_users.id"), nullable=False, index=True)
    artifact_id = Column(Integer, ForeignKey("paid_beta_artifacts.id"), nullable=False, index=True)
    checkout_session_id = Column(Integer, ForeignKey("paid_beta_checkout_sessions.id"), nullable=True)
    status = Column(String(32), nullable=False, default="active", index=True)
    provider_event_id = Column(String(128), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    revoked_at = Column(DateTime(timezone=True), nullable=True)


class CheckoutSession(Base):
    __tablename__ = "paid_beta_checkout_sessions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("paid_beta_users.id"), nullable=False, index=True)
    product_code = Column(String(32), nullable=False)
    artifact_id = Column(Integer, ForeignKey("paid_beta_artifacts.id"), nullable=True, index=True)
    provider_session_id = Column(String(128), unique=True, nullable=False)
    provider_payment_intent_id = Column(String(128), unique=True, nullable=True, index=True)
    mode = Column(String(32), nullable=False)
    status = Column(String(32), nullable=False, default="open")
    payment_status = Column(String(32), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class SignalRecord(Base):
    __tablename__ = "paid_beta_signal_records"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(40), nullable=False, index=True)
    strategy = Column(String(80), nullable=False)
    side = Column(String(16), nullable=False)
    confidence = Column(Numeric(8, 4), nullable=True)
    evidence = Column(Text, nullable=False, default="{}")
    observed_at = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class Alert(Base):
    __tablename__ = "paid_beta_alerts"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("paid_beta_users.id"), nullable=False, index=True)
    name = Column(String(160), nullable=False)
    symbol = Column(String(40), nullable=False, index=True)
    condition = Column(Text, nullable=False, default="{}")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class PasswordResetToken(Base):
    __tablename__ = "paid_beta_password_reset_tokens"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("paid_beta_users.id"), nullable=False, index=True)
    token_hash = Column(String(64), unique=True, index=True, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
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


class AuditLog(Base):
    __tablename__ = "paid_beta_audit_logs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("paid_beta_users.id"), nullable=True, index=True)
    action = Column(String(96), nullable=False, index=True)
    resource_type = Column(String(64), nullable=True)
    resource_id = Column(String(160), nullable=True)
    metadata_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, index=True)

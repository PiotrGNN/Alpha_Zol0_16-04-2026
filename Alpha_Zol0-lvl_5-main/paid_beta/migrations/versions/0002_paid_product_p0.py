"""paid product P0 resources and security

Revision ID: 0002_paid_product_p0
Revises: 0001_paid_beta_foundation
"""
from alembic import op
import sqlalchemy as sa

from paid_beta.database import Base
from paid_beta import models  # noqa: F401

revision = "0002_paid_product_p0"
down_revision = "0001_paid_beta_foundation"
branch_labels = None
depends_on = None


def _column_names(inspector, table: str) -> set[str]:
    return {item["name"] for item in inspector.get_columns(table)}


def _index_names(inspector, table: str) -> set[str]:
    return {item["name"] for item in inspector.get_indexes(table)}


def _has_artifact_fk(inspector) -> bool:
    for item in inspector.get_foreign_keys("paid_beta_checkout_sessions"):
        if (
            item.get("referred_table") == "paid_beta_artifacts"
            and item.get("constrained_columns") == ["artifact_id"]
            and item.get("referred_columns") == ["id"]
        ):
            return True
    return False


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "paid_beta_users" in tables and "token_version" not in _column_names(inspector, "paid_beta_users"):
        with op.batch_alter_table("paid_beta_users") as batch:
            batch.add_column(
                sa.Column("token_version", sa.Integer(), nullable=False, server_default="0")
            )

    if "paid_beta_checkout_sessions" in tables:
        checkout_columns = _column_names(inspector, "paid_beta_checkout_sessions")
        with op.batch_alter_table("paid_beta_checkout_sessions") as batch:
            if "artifact_id" not in checkout_columns:
                batch.add_column(sa.Column("artifact_id", sa.Integer(), nullable=True))
            if "provider_payment_intent_id" not in checkout_columns:
                batch.add_column(
                    sa.Column("provider_payment_intent_id", sa.String(length=128), nullable=True)
                )
            if "payment_status" not in checkout_columns:
                batch.add_column(sa.Column("payment_status", sa.String(length=32), nullable=True))

    Base.metadata.create_all(bind=bind, checkfirst=True)

    inspector = sa.inspect(bind)
    if "paid_beta_checkout_sessions" in inspector.get_table_names():
        indexes = _index_names(inspector, "paid_beta_checkout_sessions")
        if "ix_paid_beta_checkout_sessions_artifact_id" not in indexes:
            op.create_index(
                "ix_paid_beta_checkout_sessions_artifact_id",
                "paid_beta_checkout_sessions",
                ["artifact_id"],
            )
        if "ix_paid_beta_checkout_sessions_provider_payment_intent_id" not in indexes:
            op.create_index(
                "ix_paid_beta_checkout_sessions_provider_payment_intent_id",
                "paid_beta_checkout_sessions",
                ["provider_payment_intent_id"],
                unique=True,
            )
        inspector = sa.inspect(bind)
        if not _has_artifact_fk(inspector):
            with op.batch_alter_table("paid_beta_checkout_sessions") as batch:
                batch.create_foreign_key(
                    "fk_paid_beta_checkout_artifact",
                    "paid_beta_artifacts",
                    ["artifact_id"],
                    ["id"],
                )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "paid_beta_checkout_sessions" in tables:
        columns = _column_names(inspector, "paid_beta_checkout_sessions")
        with op.batch_alter_table("paid_beta_checkout_sessions") as batch:
            if "payment_status" in columns:
                batch.drop_column("payment_status")
            if "provider_payment_intent_id" in columns:
                batch.drop_column("provider_payment_intent_id")
            if "artifact_id" in columns:
                batch.drop_column("artifact_id")

    inspector = sa.inspect(bind)
    for table in (
        "paid_beta_audit_logs",
        "paid_beta_password_reset_tokens",
        "paid_beta_alerts",
        "paid_beta_signal_records",
        "paid_beta_artifact_grants",
        "paid_beta_artifacts",
    ):
        if table in inspector.get_table_names():
            op.drop_table(table)

    inspector = sa.inspect(bind)
    if "paid_beta_users" in inspector.get_table_names():
        if "token_version" in _column_names(inspector, "paid_beta_users"):
            with op.batch_alter_table("paid_beta_users") as batch:
                batch.drop_column("token_version")

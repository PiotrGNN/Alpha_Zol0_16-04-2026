"""paid product P0 resources and security

Revision ID: 0002_paid_product_p0
Revises: 0001_paid_beta_foundation
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_paid_product_p0"
down_revision = "0001_paid_beta_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("paid_beta_users") as batch:
        batch.add_column(sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"))

    op.create_table(
        "paid_beta_artifacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(length=160), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("resource_type", sa.String(length=32), nullable=False),
        sa.Column("required_plan", sa.String(length=32), nullable=False, server_default="starter"),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("content", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_paid_beta_artifacts_slug", "paid_beta_artifacts", ["slug"], unique=True)
    op.create_index("ix_paid_beta_artifacts_resource_type", "paid_beta_artifacts", ["resource_type"])

    with op.batch_alter_table("paid_beta_checkout_sessions") as batch:
        batch.add_column(sa.Column("artifact_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("payment_status", sa.String(length=32), nullable=True))
        batch.create_foreign_key(
            "fk_paid_beta_checkout_artifact",
            "paid_beta_artifacts",
            ["artifact_id"],
            ["id"],
        )
    op.create_index(
        "ix_paid_beta_checkout_sessions_artifact_id",
        "paid_beta_checkout_sessions",
        ["artifact_id"],
    )

    op.create_table(
        "paid_beta_artifact_grants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("paid_beta_users.id"), nullable=False),
        sa.Column("artifact_id", sa.Integer(), sa.ForeignKey("paid_beta_artifacts.id"), nullable=False),
        sa.Column("checkout_session_id", sa.Integer(), sa.ForeignKey("paid_beta_checkout_sessions.id"), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("provider_event_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("user_id", "artifact_id", name="uq_paid_beta_grant_user_artifact"),
    )
    op.create_index("ix_paid_beta_artifact_grants_user_id", "paid_beta_artifact_grants", ["user_id"])
    op.create_index("ix_paid_beta_artifact_grants_artifact_id", "paid_beta_artifact_grants", ["artifact_id"])
    op.create_index("ix_paid_beta_artifact_grants_status", "paid_beta_artifact_grants", ["status"])

    op.create_table(
        "paid_beta_signal_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("symbol", sa.String(length=40), nullable=False),
        sa.Column("strategy", sa.String(length=80), nullable=False),
        sa.Column("side", sa.String(length=16), nullable=False),
        sa.Column("confidence", sa.Numeric(8, 4), nullable=True),
        sa.Column("evidence", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_paid_beta_signal_records_symbol", "paid_beta_signal_records", ["symbol"])
    op.create_index("ix_paid_beta_signal_records_observed_at", "paid_beta_signal_records", ["observed_at"])

    op.create_table(
        "paid_beta_alerts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("paid_beta_users.id"), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("symbol", sa.String(length=40), nullable=False),
        sa.Column("condition", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_paid_beta_alerts_user_id", "paid_beta_alerts", ["user_id"])
    op.create_index("ix_paid_beta_alerts_symbol", "paid_beta_alerts", ["symbol"])

    op.create_table(
        "paid_beta_password_reset_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("paid_beta_users.id"), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_paid_beta_password_reset_tokens_user_id", "paid_beta_password_reset_tokens", ["user_id"])
    op.create_index("ix_paid_beta_password_reset_tokens_token_hash", "paid_beta_password_reset_tokens", ["token_hash"], unique=True)

    op.create_table(
        "paid_beta_audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("paid_beta_users.id"), nullable=True),
        sa.Column("action", sa.String(length=96), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=True),
        sa.Column("resource_id", sa.String(length=160), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_paid_beta_audit_logs_user_id", "paid_beta_audit_logs", ["user_id"])
    op.create_index("ix_paid_beta_audit_logs_action", "paid_beta_audit_logs", ["action"])
    op.create_index("ix_paid_beta_audit_logs_created_at", "paid_beta_audit_logs", ["created_at"])


def downgrade() -> None:
    op.drop_table("paid_beta_audit_logs")
    op.drop_table("paid_beta_password_reset_tokens")
    op.drop_table("paid_beta_alerts")
    op.drop_table("paid_beta_signal_records")
    op.drop_table("paid_beta_artifact_grants")
    with op.batch_alter_table("paid_beta_checkout_sessions") as batch:
        batch.drop_constraint("fk_paid_beta_checkout_artifact", type_="foreignkey")
        batch.drop_column("payment_status")
        batch.drop_column("artifact_id")
    op.drop_table("paid_beta_artifacts")
    with op.batch_alter_table("paid_beta_users") as batch:
        batch.drop_column("token_version")

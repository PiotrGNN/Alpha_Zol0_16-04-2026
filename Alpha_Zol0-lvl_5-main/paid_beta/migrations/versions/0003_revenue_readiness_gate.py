"""revenue readiness economics ledger

Revision ID: 0003_revenue_readiness_gate
Revises: 0002_paid_product_p0
"""

from alembic import op
import sqlalchemy as sa

revision = "0003_revenue_readiness_gate"
down_revision = "0002_paid_product_p0"
branch_labels = None
depends_on = None

TABLE = "paid_beta_economics_periods"


def _indexes(inspector) -> set[str]:
    return {item["name"] for item in inspector.get_indexes(TABLE)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE not in inspector.get_table_names():
        op.create_table(
            TABLE,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("period_start", sa.Date(), nullable=False),
            sa.Column("period_end", sa.Date(), nullable=False),
            sa.Column("source", sa.String(length=64), nullable=False),
            sa.Column("currency", sa.String(length=3), nullable=False, server_default="PLN"),
            sa.Column("gross_revenue", sa.Numeric(14, 2), nullable=False, server_default="0"),
            sa.Column("payment_fees", sa.Numeric(14, 2), nullable=False, server_default="0"),
            sa.Column("refunds", sa.Numeric(14, 2), nullable=False, server_default="0"),
            sa.Column("hosting_cost", sa.Numeric(14, 2), nullable=False, server_default="0"),
            sa.Column("support_cost", sa.Numeric(14, 2), nullable=False, server_default="0"),
            sa.Column("acquisition_spend", sa.Numeric(14, 2), nullable=False, server_default="0"),
            sa.Column("other_variable_cost", sa.Numeric(14, 2), nullable=False, server_default="0"),
            sa.Column("active_customers", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("new_customers", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("churned_customers", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("activated_customers", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("checkout_started", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("checkout_completed", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("failed_payments", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("recovered_payments", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("support_minutes", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("notes", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "period_start", "period_end", "source",
                name="uq_paid_beta_economics_period_source",
            ),
        )
    inspector = sa.inspect(bind)
    indexes = _indexes(inspector)
    if "ix_paid_beta_economics_periods_period_start" not in indexes:
        op.create_index("ix_paid_beta_economics_periods_period_start", TABLE, ["period_start"])
    if "ix_paid_beta_economics_periods_period_end" not in indexes:
        op.create_index("ix_paid_beta_economics_periods_period_end", TABLE, ["period_end"])


def downgrade() -> None:
    bind = op.get_bind()
    if TABLE in sa.inspect(bind).get_table_names():
        op.drop_table(TABLE)

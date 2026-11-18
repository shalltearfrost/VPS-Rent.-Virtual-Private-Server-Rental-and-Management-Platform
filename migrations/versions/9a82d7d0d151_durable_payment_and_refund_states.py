"""Durable payment attempts, validated amounts and pending refunds."""

import sqlalchemy as sa
from alembic import op

revision = "9a82d7d0d151"
down_revision = "7c1d2a9f4b10"
branch_labels = None
depends_on = None


def upgrade():
    for column in (
        sa.Column("reference", sa.String(64), nullable=True),
        sa.Column("charge_amount", sa.BigInteger(), nullable=True),
        sa.Column("charge_currency", sa.String(3), nullable=True),
        sa.Column(
            "review_required",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("refund_reference", sa.String(64), nullable=True),
        sa.Column(
            "refund_started_at", sa.DateTime(timezone=True), nullable=True
        ),
    ):
        op.add_column("payments", column)
    op.alter_column("payments", "review_required", server_default=None)
    for name in ("reference", "refund_reference"):
        op.create_unique_constraint(f"payments_{name}_key", "payments", [name])
    op.execute(
        "UPDATE payments SET charge_amount = invoices.amount_cents, "
        "charge_currency = invoices.currency FROM invoices "
        "WHERE payments.invoice_id = invoices.id"
    )
    op.drop_constraint("payment_status", "payments", type_="check")
    op.drop_constraint("payment_provider_details", "payments", type_="check")
    op.create_check_constraint(
        "payment_status",
        "payments",
        "status IN ('reserved', 'uncertain', 'pending', 'refund_pending', "
        "'succeeded', 'failed', 'refunded')",
    )
    op.create_check_constraint(
        "payment_provider_details",
        "payments",
        "provider = 'test' OR provider_invoice_id IS NOT NULL "
        "OR status IN ('reserved', 'uncertain', 'failed')",
    )
    op.create_check_constraint(
        "payment_charge_quote",
        "payments",
        "(charge_amount IS NULL AND charge_currency IS NULL) OR "
        "(charge_amount > 0 AND charge_amount IS NOT NULL AND "
        "charge_currency IN ('EUR', 'USD', 'UAH') "
        "AND charge_currency IS NOT NULL)",
    )
    op.drop_index("uq_pending_payment", table_name="payments")
    op.create_index(
        "uq_pending_payment",
        "payments",
        ["invoice_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('reserved', 'uncertain', 'pending', 'refund_pending')"
        ),
    )


def downgrade():
    raise RuntimeError(
        "Reconcile payment attempts before downgrading financial state."
    )

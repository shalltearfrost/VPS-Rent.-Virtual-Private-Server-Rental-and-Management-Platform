"""add monobank test checkouts"""

import sqlalchemy as sa
from alembic import op

revision = "770df647333b"
down_revision = "e266e9761931"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "monobank_checkouts",
        sa.Column("invoice_id", sa.BigInteger(), nullable=False),
        sa.Column("payment_id", sa.BigInteger(), nullable=True),
        sa.Column("reference", sa.String(length=64), nullable=False),
        sa.Column("provider_invoice_id", sa.String(length=64), nullable=False),
        sa.Column("payment_url", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("modified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("review_required", sa.Boolean(), nullable=False),
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('created', 'processing', 'hold', 'success', "
            "'failure', 'expired', 'reversed')",
            name="monobank_checkout_status",
        ),
        sa.ForeignKeyConstraint(
            ["invoice_id"], ["invoices.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["payment_id"], ["payments.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("payment_id"),
        sa.UniqueConstraint("provider_invoice_id"),
        sa.UniqueConstraint("reference"),
    )
    op.create_index(
        op.f("ix_monobank_checkouts_invoice_id"),
        "monobank_checkouts",
        ["invoice_id"],
        unique=False,
    )
    op.create_index(
        "uq_monobank_pending_invoice",
        "monobank_checkouts",
        ["invoice_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('created', 'processing', 'hold')"
        ),
    )


def downgrade():
    op.drop_index(
        "uq_monobank_pending_invoice",
        table_name="monobank_checkouts",
        postgresql_where=sa.text(
            "status IN ('created', 'processing', 'hold')"
        ),
    )
    op.drop_index(
        op.f("ix_monobank_checkouts_invoice_id"),
        table_name="monobank_checkouts",
    )
    op.drop_table("monobank_checkouts")

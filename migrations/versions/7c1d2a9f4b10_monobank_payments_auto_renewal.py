"""Monobank payments, saved cards and auto-renewal"""

import sqlalchemy as sa
from alembic import op

revision = "7c1d2a9f4b10"
down_revision = "e266e9761931"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "payment_cards",
        sa.Column("customer_id", sa.BigInteger(), nullable=False),
        sa.Column("token_ciphertext", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("masked_pan", sa.String(length=32), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_payment_cards_customer_id"),
        "payment_cards",
        ["customer_id"],
    )
    op.create_index(
        "uq_active_card_token",
        "payment_cards",
        ["token_hash"],
        unique=True,
        postgresql_where=sa.text("removed_at IS NULL"),
    )

    op.add_column(
        "rentals",
        sa.Column("auto_renew_card_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "rentals_auto_renew_card_id_fkey",
        "rentals",
        "payment_cards",
        ["auto_renew_card_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        op.f("ix_rentals_auto_renew_card_id"),
        "rentals",
        ["auto_renew_card_id"],
    )

    op.drop_index("uq_successful_payment", table_name="payments")
    op.drop_constraint("payment_outcome", "payments", type_="check")
    op.alter_column("payments", "outcome", new_column_name="status")
    columns = [
        sa.Column(
            "provider",
            sa.String(length=16),
            server_default="test",
            nullable=False,
        ),
        sa.Column(
            "initiated_by",
            sa.String(length=16),
            server_default="customer",
            nullable=False,
        ),
        sa.Column("provider_invoice_id", sa.String(length=64), nullable=True),
        sa.Column("page_url", sa.Text(), nullable=True),
        sa.Column(
            "save_card",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("card_id", sa.BigInteger(), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column(
            "provider_modified_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]
    for column in columns:
        op.add_column("payments", column)
    # Existing rows are test payments; new rows are Monobank by default.
    op.alter_column("payments", "provider", server_default=None)
    op.alter_column("payments", "initiated_by", server_default=None)
    op.alter_column("payments", "save_card", server_default=None)
    op.create_check_constraint(
        "payment_status",
        "payments",
        "status IN ('pending', 'succeeded', 'failed', 'refunded')",
    )
    op.create_check_constraint(
        "payment_provider", "payments", "provider IN ('test', 'monobank')"
    )
    op.create_check_constraint(
        "payment_initiator",
        "payments",
        "initiated_by IN ('customer', 'auto')",
    )
    op.create_check_constraint(
        "payment_provider_details",
        "payments",
        "provider = 'test' OR provider_invoice_id IS NOT NULL "
        "OR status = 'failed'",
    )
    op.create_unique_constraint(
        "payments_provider_invoice_id_key",
        "payments",
        ["provider_invoice_id"],
    )
    op.create_foreign_key(
        "payments_card_id_fkey",
        "payments",
        "payment_cards",
        ["card_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(op.f("ix_payments_card_id"), "payments", ["card_id"])
    op.create_index("ix_payments_status", "payments", ["status", "updated_at"])
    op.create_index(
        "uq_successful_payment",
        "payments",
        ["invoice_id"],
        unique=True,
        postgresql_where=sa.text("status = 'succeeded'"),
    )
    op.create_index(
        "uq_pending_payment",
        "payments",
        ["invoice_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade():
    op.execute("DELETE FROM payments WHERE provider <> 'test'")
    op.drop_index("uq_pending_payment", table_name="payments")
    op.drop_index("uq_successful_payment", table_name="payments")
    op.drop_index("ix_payments_status", table_name="payments")
    op.drop_index(op.f("ix_payments_card_id"), table_name="payments")
    op.drop_constraint("payments_card_id_fkey", "payments", type_="foreignkey")
    op.drop_constraint(
        "payments_provider_invoice_id_key", "payments", type_="unique"
    )
    for name in (
        "payment_provider_details",
        "payment_initiator",
        "payment_provider",
        "payment_status",
    ):
        op.drop_constraint(name, "payments", type_="check")
    for name in (
        "updated_at",
        "provider_modified_at",
        "failure_reason",
        "card_id",
        "save_card",
        "page_url",
        "provider_invoice_id",
        "initiated_by",
        "provider",
    ):
        op.drop_column("payments", name)
    op.alter_column("payments", "status", new_column_name="outcome")
    op.create_check_constraint(
        "payment_outcome", "payments", "outcome IN ('succeeded', 'failed')"
    )
    op.create_index(
        "uq_successful_payment",
        "payments",
        ["invoice_id"],
        unique=True,
        postgresql_where=sa.text("outcome = 'succeeded'"),
    )
    op.drop_index(op.f("ix_rentals_auto_renew_card_id"), table_name="rentals")
    op.drop_constraint(
        "rentals_auto_renew_card_id_fkey", "rentals", type_="foreignkey"
    )
    op.drop_column("rentals", "auto_renew_card_id")
    op.drop_index("uq_active_card_token", table_name="payment_cards")
    op.drop_index(
        op.f("ix_payment_cards_customer_id"), table_name="payment_cards"
    )
    op.drop_table("payment_cards")

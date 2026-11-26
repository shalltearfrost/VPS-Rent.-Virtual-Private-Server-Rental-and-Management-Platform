"""Store Monobank checkout exchange quotes."""

import sqlalchemy as sa
from alembic import op

revision = "19364610a068"
down_revision = "770df647333b"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "monobank_checkouts",
        sa.Column("amount_kopecks", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "monobank_checkouts",
        sa.Column("eur_uah_rate", sa.Numeric(12, 6), nullable=True),
    )
    op.create_check_constraint(
        "monobank_checkout_quote",
        "monobank_checkouts",
        "(amount_kopecks IS NULL AND eur_uah_rate IS NULL) OR "
        "(amount_kopecks IS NOT NULL AND amount_kopecks > 0 "
        "AND eur_uah_rate IS NOT NULL AND eur_uah_rate > 0)",
    )


def downgrade():
    op.drop_constraint(
        "monobank_checkout_quote", "monobank_checkouts", type_="check"
    )
    op.drop_column("monobank_checkouts", "eur_uah_rate")
    op.drop_column("monobank_checkouts", "amount_kopecks")

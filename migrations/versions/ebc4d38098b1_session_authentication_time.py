"""Remember when a session authenticated for Google account linking."""

import sqlalchemy as sa
from alembic import op

revision = "ebc4d38098b1"
down_revision = "da8f0c21e37b"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "sessions", sa.Column("authenticated_at", sa.DateTime(timezone=True))
    )


def downgrade():
    op.drop_column("sessions", "authenticated_at")

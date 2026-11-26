"""Google sign-in: users.google_sub, optional password_hash"""

import secrets

import sqlalchemy as sa
from alembic import op
from pwdlib import PasswordHash

revision = "c4a7d2e9f1b6"
down_revision = "b3f8e1c2d4a5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users",
        sa.Column("google_sub", sa.String(length=255), nullable=True),
    )
    op.create_unique_constraint(
        "users_google_sub_key", "users", ["google_sub"]
    )
    op.alter_column(
        "users", "password_hash", existing_type=sa.Text(), nullable=True
    )
    op.create_check_constraint(
        "user_has_credential",
        "users",
        "password_hash IS NOT NULL OR google_sub IS NOT NULL",
    )


def downgrade():
    op.drop_constraint("user_has_credential", "users", type_="check")
    # Google-only accounts get a hash of a random secret nobody knows, so
    # the NOT NULL constraint can return and password sign-in still fails.
    unusable = PasswordHash.recommended().hash(secrets.token_urlsafe(32))
    op.execute(
        sa.text(
            "UPDATE users SET password_hash = :hash "
            "WHERE password_hash IS NULL"
        ).bindparams(hash=unusable)
    )
    op.alter_column(
        "users", "password_hash", existing_type=sa.Text(), nullable=False
    )
    op.drop_constraint("users_google_sub_key", "users", type_="unique")
    op.drop_column("users", "google_sub")

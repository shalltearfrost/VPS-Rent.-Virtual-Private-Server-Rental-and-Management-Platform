"""Create rental platform schema"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e266e9761931"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "plans",
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column("description", sa.String(length=160), nullable=False),
        sa.Column("cpu", sa.Integer(), nullable=False),
        sa.Column("ram_gb", sa.Integer(), nullable=False),
        sa.Column("disk_gb", sa.Integer(), nullable=False),
        sa.Column("monthly_cents", sa.Integer(), nullable=False),
        sa.Column("annual_cents", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "cpu > 0 AND ram_gb > 0 AND disk_gb > 0",
            name="plan_resources_positive",
        ),
        sa.CheckConstraint(
            "monthly_cents > 0 AND annual_cents > 0",
            name="plan_prices_positive",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "servers",
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column("address", postgresql.INET(), nullable=False),
        sa.Column("cpu", sa.Integer(), nullable=False),
        sa.Column("ram_gb", sa.Integer(), nullable=False),
        sa.Column("disk_gb", sa.Integer(), nullable=False),
        sa.Column("ssh_user", sa.String(length=32), nullable=False),
        sa.Column("password_ciphertext", sa.Text(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "state IN ('available', 'assigned', 'suspended', 'preparing')",
            name="server_state",
        ),
        sa.CheckConstraint(
            "cpu > 0 AND ram_gb > 0 AND disk_gb > 0",
            name="server_resources_positive",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("address"),
        sa.UniqueConstraint("name"),
    )
    op.create_index(
        "ix_servers_available",
        "servers",
        ["state", "cpu", "ram_gb", "disk_gb"],
        unique=False,
    )
    op.create_table(
        "users",
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('customer', 'operator', 'support', 'manager')",
            name="user_role",
        ),
        sa.CheckConstraint("email = lower(email)", name="email_lowercase"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_table(
        "activity",
        sa.Column("actor_id", sa.BigInteger(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("entity_id", sa.BigInteger(), nullable=False),
        sa.Column("result", sa.Text(), nullable=False),
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_activity_actor_id"), "activity", ["actor_id"], unique=False
    )
    op.create_index(
        "ix_activity_time", "activity", ["created_at"], unique=False
    )
    op.create_table(
        "orders",
        sa.Column("customer_id", sa.BigInteger(), nullable=False),
        sa.Column("plan_id", sa.BigInteger(), nullable=False),
        sa.Column("plan_name", sa.String(length=40), nullable=False),
        sa.Column("cpu", sa.Integer(), nullable=False),
        sa.Column("ram_gb", sa.Integer(), nullable=False),
        sa.Column("disk_gb", sa.Integer(), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("renewal_cents", sa.Integer(), nullable=False),
        sa.Column("term", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('awaiting_payment', 'awaiting_allocation', "
            "'active', 'expired')",
            name="order_status",
        ),
        sa.CheckConstraint("term IN ('monthly', 'annual')", name="order_term"),
        sa.CheckConstraint(
            "cpu > 0 AND ram_gb > 0 AND disk_gb > 0 "
            "AND price_cents > 0 AND renewal_cents > 0",
            name="order_snapshot_positive",
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["plans.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_orders_customer_created",
        "orders",
        ["customer_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_orders_customer_id"), "orders", ["customer_id"], unique=False
    )
    op.create_index(
        op.f("ix_orders_plan_id"), "orders", ["plan_id"], unique=False
    )
    op.create_index(
        "ix_orders_queue", "orders", ["status", "created_at"], unique=False
    )
    op.create_table(
        "sessions",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("csrf_token", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        op.f("ix_sessions_expires_at"),
        "sessions",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sessions_user_id"), "sessions", ["user_id"], unique=False
    )
    op.create_table(
        "rentals",
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("server_id", sa.BigInteger(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("power", sa.String(length=16), nullable=False),
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "power IN ('running', 'stopped')", name="rental_power"
        ),
        sa.CheckConstraint(
            "status IN ('active', 'suspension_pending', 'suspended', 'ended')",
            name="rental_status",
        ),
        sa.CheckConstraint("expires_at > started_at", name="rental_period"),
        sa.ForeignKeyConstraint(
            ["order_id"], ["orders.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["server_id"], ["servers.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_id"),
    )
    op.create_index(
        "ix_rentals_expiry", "rentals", ["status", "expires_at"], unique=False
    )
    op.create_index(
        op.f("ix_rentals_server_id"), "rentals", ["server_id"], unique=False
    )
    op.create_index(
        "uq_rental_held_server",
        "rentals",
        ["server_id"],
        unique=True,
        postgresql_where=sa.text("status <> 'ended'"),
    )
    op.create_table(
        "invoices",
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("rental_id", sa.BigInteger(), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(kind = 'initial' AND rental_id IS NULL) OR "
            "(kind = 'renewal' AND rental_id IS NOT NULL)",
            name="invoice_kind",
        ),
        sa.CheckConstraint(
            "(status = 'paid') = (paid_at IS NOT NULL)", name="invoice_paid_at"
        ),
        sa.CheckConstraint("currency = 'EUR'", name="invoice_currency"),
        sa.CheckConstraint(
            "status IN ('unpaid', 'paid')", name="invoice_status"
        ),
        sa.CheckConstraint("amount_cents > 0", name="invoice_amount"),
        sa.ForeignKeyConstraint(
            ["order_id"], ["orders.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["rental_id"], ["rentals.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_invoices_order_id"), "invoices", ["order_id"], unique=False
    )
    op.create_index(
        op.f("ix_invoices_rental_id"), "invoices", ["rental_id"], unique=False
    )
    op.create_index(
        "uq_initial_invoice",
        "invoices",
        ["order_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'initial'"),
    )
    op.create_index(
        "uq_open_renewal",
        "invoices",
        ["rental_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'renewal' AND status = 'unpaid'"),
    )
    op.create_table(
        "operation_requests",
        sa.Column("rental_id", sa.BigInteger(), nullable=False),
        sa.Column("requested_by", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("resolved_by", sa.BigInteger(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(status = 'pending' AND resolved_by IS NULL "
            "AND resolved_at IS NULL AND result IS NULL) OR "
            "(status <> 'pending' AND resolved_by IS NOT NULL "
            "AND resolved_at IS NOT NULL AND length(trim(result)) > 0 "
            "AND result IS NOT NULL)",
            name="operation_resolution",
        ),
        sa.CheckConstraint(
            "kind IN ('start', 'stop', 'restart')", name="operation_kind"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'completed', 'rejected')",
            name="operation_status",
        ),
        sa.ForeignKeyConstraint(
            ["rental_id"], ["rentals.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_operation_requests_rental_id"),
        "operation_requests",
        ["rental_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_operation_requests_requested_by"),
        "operation_requests",
        ["requested_by"],
        unique=False,
    )
    op.create_index(
        op.f("ix_operation_requests_resolved_by"),
        "operation_requests",
        ["resolved_by"],
        unique=False,
    )
    op.create_index(
        "uq_pending_operation",
        "operation_requests",
        ["rental_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_table(
        "tickets",
        sa.Column("customer_id", sa.BigInteger(), nullable=False),
        sa.Column("rental_id", sa.BigInteger(), nullable=True),
        sa.Column("subject", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('open', 'in_progress', 'closed')", name="ticket_status"
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["rental_id"], ["rentals.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_tickets_customer_id"),
        "tickets",
        ["customer_id"],
        unique=False,
    )
    op.create_index(
        "ix_tickets_queue", "tickets", ["status", "created_at"], unique=False
    )
    op.create_index(
        op.f("ix_tickets_rental_id"), "tickets", ["rental_id"], unique=False
    )
    op.create_table(
        "payments",
        sa.Column("invoice_id", sa.BigInteger(), nullable=False),
        sa.Column("customer_id", sa.BigInteger(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "outcome IN ('succeeded', 'failed')", name="payment_outcome"
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["invoice_id"], ["invoices.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index(
        op.f("ix_payments_customer_id"),
        "payments",
        ["customer_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_payments_invoice_id"),
        "payments",
        ["invoice_id"],
        unique=False,
    )
    op.create_index(
        "uq_successful_payment",
        "payments",
        ["invoice_id"],
        unique=True,
        postgresql_where=sa.text("outcome = 'succeeded'"),
    )
    op.create_table(
        "ticket_messages",
        sa.Column("ticket_id", sa.BigInteger(), nullable=False),
        sa.Column("author_id", sa.BigInteger(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("length(trim(body)) > 0", name="message_body"),
        sa.ForeignKeyConstraint(
            ["author_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"], ["tickets.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_messages_thread",
        "ticket_messages",
        ["ticket_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ticket_messages_author_id"),
        "ticket_messages",
        ["author_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ticket_messages_ticket_id"),
        "ticket_messages",
        ["ticket_id"],
        unique=False,
    )


def downgrade():
    op.drop_index(
        op.f("ix_ticket_messages_ticket_id"), table_name="ticket_messages"
    )
    op.drop_index(
        op.f("ix_ticket_messages_author_id"), table_name="ticket_messages"
    )
    op.drop_index("ix_messages_thread", table_name="ticket_messages")
    op.drop_table("ticket_messages")
    op.drop_index(
        "uq_successful_payment",
        table_name="payments",
        postgresql_where=sa.text("outcome = 'succeeded'"),
    )
    op.drop_index(op.f("ix_payments_invoice_id"), table_name="payments")
    op.drop_index(op.f("ix_payments_customer_id"), table_name="payments")
    op.drop_table("payments")
    op.drop_index(op.f("ix_tickets_rental_id"), table_name="tickets")
    op.drop_index("ix_tickets_queue", table_name="tickets")
    op.drop_index(op.f("ix_tickets_customer_id"), table_name="tickets")
    op.drop_table("tickets")
    op.drop_index(
        "uq_pending_operation",
        table_name="operation_requests",
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.drop_index(
        op.f("ix_operation_requests_resolved_by"),
        table_name="operation_requests",
    )
    op.drop_index(
        op.f("ix_operation_requests_requested_by"),
        table_name="operation_requests",
    )
    op.drop_index(
        op.f("ix_operation_requests_rental_id"),
        table_name="operation_requests",
    )
    op.drop_table("operation_requests")
    op.drop_index(
        "uq_open_renewal",
        table_name="invoices",
        postgresql_where=sa.text("kind = 'renewal' AND status = 'unpaid'"),
    )
    op.drop_index(
        "uq_initial_invoice",
        table_name="invoices",
        postgresql_where=sa.text("kind = 'initial'"),
    )
    op.drop_index(op.f("ix_invoices_rental_id"), table_name="invoices")
    op.drop_index(op.f("ix_invoices_order_id"), table_name="invoices")
    op.drop_table("invoices")
    op.drop_index(
        "uq_rental_held_server",
        table_name="rentals",
        postgresql_where=sa.text("status <> 'ended'"),
    )
    op.drop_index(op.f("ix_rentals_server_id"), table_name="rentals")
    op.drop_index("ix_rentals_expiry", table_name="rentals")
    op.drop_table("rentals")
    op.drop_index(op.f("ix_sessions_user_id"), table_name="sessions")
    op.drop_index(op.f("ix_sessions_expires_at"), table_name="sessions")
    op.drop_table("sessions")
    op.drop_index("ix_orders_queue", table_name="orders")
    op.drop_index(op.f("ix_orders_plan_id"), table_name="orders")
    op.drop_index(op.f("ix_orders_customer_id"), table_name="orders")
    op.drop_index("ix_orders_customer_created", table_name="orders")
    op.drop_table("orders")
    op.drop_index("ix_activity_time", table_name="activity")
    op.drop_index(op.f("ix_activity_actor_id"), table_name="activity")
    op.drop_table("activity")
    op.drop_table("users")
    op.drop_index("ix_servers_available", table_name="servers")
    op.drop_table("servers")
    op.drop_table("plans")

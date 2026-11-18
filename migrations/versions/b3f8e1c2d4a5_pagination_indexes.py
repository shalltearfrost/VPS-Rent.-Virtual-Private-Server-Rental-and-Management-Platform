"""Ticket list columns and indexes for keyset pagination"""

import sqlalchemy as sa
from alembic import op

revision = "b3f8e1c2d4a5"
down_revision = "7c1d2a9f4b10"
branch_labels = None
depends_on = None

PENDING = sa.text("status = 'pending'")
RESOLVED = sa.text("status <> 'pending'")
AWAITING = sa.text("awaiting_support AND status <> 'closed'")


def upgrade():
    op.add_column(
        "tickets",
        sa.Column(
            "last_message_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column(
        "tickets",
        sa.Column(
            "awaiting_support",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
    )
    # Backfill from each ticket's newest message.
    op.execute(
        """
        UPDATE tickets AS t
        SET last_message_at = last.created_at,
            awaiting_support = last.role = 'customer'
        FROM (
            SELECT DISTINCT ON (m.ticket_id)
                m.ticket_id, m.created_at, u.role
            FROM ticket_messages AS m
            JOIN users AS u ON u.id = m.author_id
            ORDER BY m.ticket_id, m.created_at DESC, m.id DESC
        ) AS last
        WHERE last.ticket_id = t.id
        """
    )

    op.drop_index("ix_tickets_queue", table_name="tickets")
    op.drop_index("ix_tickets_customer_id", table_name="tickets")
    op.create_index(
        "ix_tickets_customer_recent",
        "tickets",
        ["customer_id", "last_message_at", "id"],
    )
    op.create_index(
        "ix_tickets_status_recent",
        "tickets",
        ["status", "last_message_at", "id"],
    )
    op.create_index("ix_tickets_recent", "tickets", ["last_message_at", "id"])
    op.create_index(
        "ix_tickets_awaiting",
        "tickets",
        ["last_message_at", "id"],
        postgresql_where=AWAITING,
    )

    op.drop_index("ix_messages_thread", table_name="ticket_messages")
    op.drop_index("ix_ticket_messages_ticket_id", table_name="ticket_messages")
    op.create_index(
        "ix_messages_thread",
        "ticket_messages",
        ["ticket_id", "created_at", "id"],
    )

    op.drop_index("ix_activity_time", table_name="activity")
    op.create_index("ix_activity_time", "activity", ["created_at", "id"])
    op.create_index(
        "ix_activity_scope", "activity", ["entity_type", "created_at", "id"]
    )
    op.create_index(
        "ix_activity_action",
        "activity",
        ["entity_type", "action", "created_at", "id"],
    )

    op.drop_index("ix_orders_customer_id", table_name="orders")

    op.create_index(
        "ix_operations_pending",
        "operation_requests",
        ["created_at", "id"],
        postgresql_where=PENDING,
    )
    op.create_index(
        "ix_operations_resolved",
        "operation_requests",
        ["resolved_at", "id"],
        postgresql_where=RESOLVED,
    )


def downgrade():
    op.drop_index("ix_operations_resolved", table_name="operation_requests")
    op.drop_index("ix_operations_pending", table_name="operation_requests")

    op.create_index("ix_orders_customer_id", "orders", ["customer_id"])

    op.drop_index("ix_activity_action", table_name="activity")
    op.drop_index("ix_activity_scope", table_name="activity")
    op.drop_index("ix_activity_time", table_name="activity")
    op.create_index("ix_activity_time", "activity", ["created_at"])

    op.drop_index("ix_messages_thread", table_name="ticket_messages")
    op.create_index(
        "ix_ticket_messages_ticket_id", "ticket_messages", ["ticket_id"]
    )
    op.create_index(
        "ix_messages_thread", "ticket_messages", ["ticket_id", "created_at"]
    )

    op.drop_index("ix_tickets_awaiting", table_name="tickets")
    op.drop_index("ix_tickets_recent", table_name="tickets")
    op.drop_index("ix_tickets_status_recent", table_name="tickets")
    op.drop_index("ix_tickets_customer_recent", table_name="tickets")
    op.create_index("ix_tickets_customer_id", "tickets", ["customer_id"])
    op.create_index("ix_tickets_queue", "tickets", ["status", "created_at"])

    op.drop_column("tickets", "awaiting_support")
    op.drop_column("tickets", "last_message_at")

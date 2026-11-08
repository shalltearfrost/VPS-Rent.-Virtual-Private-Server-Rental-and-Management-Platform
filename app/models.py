from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def reference(table: str):
    return mapped_column(
        ForeignKey(f"{table}.id", ondelete="RESTRICT"), index=True
    )


class Record:
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)


class Timestamped:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class User(Record, Timestamped, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "role IN ('customer', 'operator', 'support', 'manager')",
            name="user_role",
        ),
        CheckConstraint("email = lower(email)", name="email_lowercase"),
    )

    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(16), default="customer")


class LoginSession(Record, Base):
    __tablename__ = "sessions"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True
    )


class Plan(Record, Timestamped, Base):
    __tablename__ = "plans"
    __table_args__ = (
        CheckConstraint(
            "cpu > 0 AND ram_gb > 0 AND disk_gb > 0",
            name="plan_resources_positive",
        ),
        CheckConstraint(
            "monthly_cents > 0 AND annual_cents > 0",
            name="plan_prices_positive",
        ),
    )

    name: Mapped[str] = mapped_column(String(40), unique=True)
    description: Mapped[str] = mapped_column(String(160))
    cpu: Mapped[int] = mapped_column(Integer)
    ram_gb: Mapped[int] = mapped_column(Integer)
    disk_gb: Mapped[int] = mapped_column(Integer)
    monthly_cents: Mapped[int] = mapped_column(Integer)
    annual_cents: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Order(Record, Timestamped, Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("term IN ('monthly', 'annual')", name="order_term"),
        CheckConstraint(
            "status IN ('awaiting_payment', 'awaiting_allocation', "
            "'active', 'expired')",
            name="order_status",
        ),
        CheckConstraint(
            "cpu > 0 AND ram_gb > 0 AND disk_gb > 0 "
            "AND price_cents > 0 AND renewal_cents > 0",
            name="order_snapshot_positive",
        ),
        Index("ix_orders_customer_created", "customer_id", "created_at"),
        Index("ix_orders_queue", "status", "created_at"),
    )

    customer_id: Mapped[int] = reference("users")
    plan_id: Mapped[int] = reference("plans")
    plan_name: Mapped[str] = mapped_column(String(40))
    cpu: Mapped[int] = mapped_column(Integer)
    ram_gb: Mapped[int] = mapped_column(Integer)
    disk_gb: Mapped[int] = mapped_column(Integer)
    price_cents: Mapped[int] = mapped_column(Integer)
    renewal_cents: Mapped[int] = mapped_column(Integer)
    term: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24), default="awaiting_payment")


class Server(Record, Timestamped, Base):
    __tablename__ = "servers"
    __table_args__ = (
        CheckConstraint(
            "cpu > 0 AND ram_gb > 0 AND disk_gb > 0",
            name="server_resources_positive",
        ),
        CheckConstraint(
            "state IN ('available', 'assigned', 'suspended', 'preparing')",
            name="server_state",
        ),
        Index("ix_servers_available", "state", "cpu", "ram_gb", "disk_gb"),
    )

    name: Mapped[str] = mapped_column(String(40), unique=True)
    address: Mapped[str] = mapped_column(INET, unique=True)
    cpu: Mapped[int] = mapped_column(Integer)
    ram_gb: Mapped[int] = mapped_column(Integer)
    disk_gb: Mapped[int] = mapped_column(Integer)
    ssh_user: Mapped[str] = mapped_column(String(32))
    password_ciphertext: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(16), default="available")


class Rental(Record, Base):
    __tablename__ = "rentals"
    __table_args__ = (
        CheckConstraint("expires_at > started_at", name="rental_period"),
        CheckConstraint(
            "status IN ('active', 'suspension_pending', 'suspended', 'ended')",
            name="rental_status",
        ),
        CheckConstraint(
            "power IN ('running', 'stopped')", name="rental_power"
        ),
        Index(
            "uq_rental_held_server",
            "server_id",
            unique=True,
            postgresql_where=text("status <> 'ended'"),
        ),
        Index("ix_rentals_expiry", "status", "expires_at"),
    )

    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="RESTRICT"), unique=True
    )
    server_id: Mapped[int] = reference("servers")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(24), default="active")
    power: Mapped[str] = mapped_column(String(16), default="running")


class Invoice(Record, Timestamped, Base):
    __tablename__ = "invoices"
    __table_args__ = (
        CheckConstraint("amount_cents > 0", name="invoice_amount"),
        CheckConstraint("currency = 'EUR'", name="invoice_currency"),
        CheckConstraint("status IN ('unpaid', 'paid')", name="invoice_status"),
        CheckConstraint(
            "(kind = 'initial' AND rental_id IS NULL) OR "
            "(kind = 'renewal' AND rental_id IS NOT NULL)",
            name="invoice_kind",
        ),
        CheckConstraint(
            "(status = 'paid') = (paid_at IS NOT NULL)",
            name="invoice_paid_at",
        ),
        Index(
            "uq_initial_invoice",
            "order_id",
            unique=True,
            postgresql_where=text("kind = 'initial'"),
        ),
        Index(
            "uq_open_renewal",
            "rental_id",
            unique=True,
            postgresql_where=text("kind = 'renewal' AND status = 'unpaid'"),
        ),
    )

    order_id: Mapped[int] = reference("orders")
    rental_id: Mapped[int | None] = reference("rentals")
    kind: Mapped[str] = mapped_column(String(16))
    amount_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    status: Mapped[str] = mapped_column(String(16), default="unpaid")
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Payment(Record, Timestamped, Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('succeeded', 'failed')", name="payment_outcome"
        ),
        Index(
            "uq_successful_payment",
            "invoice_id",
            unique=True,
            postgresql_where=text("outcome = 'succeeded'"),
        ),
    )

    invoice_id: Mapped[int] = reference("invoices")
    customer_id: Mapped[int] = reference("users")
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True)
    outcome: Mapped[str] = mapped_column(String(16))


class OperationRequest(Record, Timestamped, Base):
    __tablename__ = "operation_requests"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('start', 'stop', 'restart')", name="operation_kind"
        ),
        CheckConstraint(
            "status IN ('pending', 'completed', 'rejected')",
            name="operation_status",
        ),
        CheckConstraint(
            "(status = 'pending' AND resolved_by IS NULL "
            "AND resolved_at IS NULL AND result IS NULL) OR "
            "(status <> 'pending' AND resolved_by IS NOT NULL "
            "AND resolved_at IS NOT NULL AND length(trim(result)) > 0 "
            "AND result IS NOT NULL)",
            name="operation_resolution",
        ),
        Index(
            "uq_pending_operation",
            "rental_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    rental_id: Mapped[int] = reference("rentals")
    requested_by: Mapped[int] = reference("users")
    kind: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    result: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[int | None] = reference("users")
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )


class Ticket(Record, Timestamped, Base):
    __tablename__ = "tickets"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'in_progress', 'closed')",
            name="ticket_status",
        ),
        Index("ix_tickets_queue", "status", "created_at"),
    )

    customer_id: Mapped[int] = reference("users")
    rental_id: Mapped[int | None] = reference("rentals")
    subject: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(16), default="open")


class TicketMessage(Record, Timestamped, Base):
    __tablename__ = "ticket_messages"
    __table_args__ = (
        CheckConstraint("length(trim(body)) > 0", name="message_body"),
        Index("ix_messages_thread", "ticket_id", "created_at"),
    )

    ticket_id: Mapped[int] = reference("tickets")
    author_id: Mapped[int] = reference("users")
    body: Mapped[str] = mapped_column(Text)


class Activity(Record, Timestamped, Base):
    __tablename__ = "activity"
    __table_args__ = (Index("ix_activity_time", "created_at"),)

    actor_id: Mapped[int | None] = reference("users")
    action: Mapped[str] = mapped_column(String(64))
    entity_type: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[int] = mapped_column(BigInteger)
    result: Mapped[str] = mapped_column(Text)

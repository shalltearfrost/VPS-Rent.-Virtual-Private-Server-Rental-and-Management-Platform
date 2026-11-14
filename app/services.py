import calendar
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Activity,
    Invoice,
    OperationRequest,
    Order,
    Payment,
    PaymentCard,
    Plan,
    Rental,
    Server,
    User,
)
from app.security import now


def record(
    db: Session,
    actor: User | None,
    action: str,
    entity_type: str,
    entity_id: int,
    result: str,
) -> None:
    db.add(
        Activity(
            actor_id=actor.id if actor else None,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            result=result,
        )
    )


def owned_order(
    db: Session, order_id: int, user: User, *, lock: bool = False
) -> Order:
    query = select(Order).where(Order.id == order_id)
    if user.role == "customer":
        query = query.where(Order.customer_id == user.id)
    if lock:
        query = query.with_for_update().execution_options(
            populate_existing=True
        )
    order = db.scalar(query)
    if not order:
        raise HTTPException(404, "Order not found")
    return order


def owned_rental(
    db: Session, rental_id: int, user: User, *, lock: bool = False
) -> tuple[Rental, Order]:
    rental = db.get(Rental, rental_id)
    if not rental:
        raise HTTPException(404, "Rental not found")
    order = owned_order(db, rental.order_id, user, lock=lock)
    if lock:
        rental = db.scalar(
            select(Rental)
            .where(Rental.id == rental_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    return rental, order


def require_active(rental: Rental) -> None:
    if rental.status != "active" or rental.expires_at <= now():
        raise HTTPException(409, "This rental is no longer active")


def create_order(
    db: Session, customer: User, plan_id: int, term: str
) -> Order:
    plan = db.scalar(select(Plan).where(Plan.id == plan_id).with_for_update())
    if not plan or not plan.enabled:
        raise HTTPException(409, "This plan is no longer available")
    order = Order(
        customer_id=customer.id,
        plan_id=plan.id,
        plan_name=plan.name,
        cpu=plan.cpu,
        ram_gb=plan.ram_gb,
        disk_gb=plan.disk_gb,
        price_cents=(
            plan.annual_cents if term == "annual" else plan.monthly_cents
        ),
        renewal_cents=plan.monthly_cents,
        term=term,
    )
    db.add(order)
    db.flush()
    db.add(
        Invoice(
            order_id=order.id, kind="initial", amount_cents=order.price_cents
        )
    )
    record(db, customer, "order_created", "order", order.id, "Invoice created")
    db.flush()
    return order


def initial_card(db: Session, order: Order) -> int | None:
    """Card saved with the initial payment enables auto-renewal."""
    return db.scalar(
        select(PaymentCard.id)
        .join(Payment, Payment.card_id == PaymentCard.id)
        .join(Invoice, Invoice.id == Payment.invoice_id)
        .where(
            Invoice.order_id == order.id,
            Invoice.kind == "initial",
            Payment.status == "succeeded",
            Payment.save_card.is_(True),
            PaymentCard.removed_at.is_(None),
        )
    )


def allocate(
    db: Session, operator: User, order_id: int, server_id: int
) -> Rental:
    order = owned_order(db, order_id, operator, lock=True)
    if order.status != "awaiting_allocation":
        raise HTTPException(409, "Only paid queued orders can be allocated")
    server = db.scalar(
        select(Server).where(Server.id == server_id).with_for_update()
    )
    if not server or server.state != "available":
        raise HTTPException(409, "This server is not available")
    if any(
        getattr(server, field) != getattr(order, field)
        for field in ("cpu", "ram_gb", "disk_gb")
    ):
        raise HTTPException(409, "The server must match the ordered resources")
    started_at = now()
    expires_at = started_at + timedelta(days=30)
    if order.term == "annual":
        year = started_at.year + 1
        last_day = calendar.monthrange(year, started_at.month)[1]
        expires_at = started_at.replace(
            year=year, day=min(started_at.day, last_day)
        )
    rental = Rental(
        order_id=order.id,
        server_id=server.id,
        started_at=started_at,
        expires_at=expires_at,
    )
    server.state = "assigned"
    order.status = "active"
    rental.auto_renew_card_id = initial_card(db, order)
    db.add(rental)
    db.flush()
    record(db, operator, "allocated", "rental", rental.id, server.name)
    return rental


def request_operation(
    db: Session, user: User, rental_id: int, kind: str
) -> OperationRequest:
    rental, _ = owned_rental(db, rental_id, user, lock=True)
    require_active(rental)
    pending = db.scalar(
        select(OperationRequest).where(
            OperationRequest.rental_id == rental.id,
            OperationRequest.status == "pending",
        )
    )
    if pending:
        raise HTTPException(
            409, "An operation is already waiting for execution"
        )
    if (kind == "start") == (rental.power == "running"):
        raise HTTPException(
            409, "This operation does not match the power state"
        )
    operation = OperationRequest(
        rental_id=rental.id, requested_by=user.id, kind=kind
    )
    db.add(operation)
    db.flush()
    record(db, user, "operation_requested", "operation", operation.id, kind)
    return operation


def resolve_operation(
    db: Session, user: User, operation_id: int, status: str, result: str
) -> OperationRequest:
    operation = db.get(OperationRequest, operation_id)
    if not operation:
        raise HTTPException(404, "Operation not found")
    rental, _ = owned_rental(db, operation.rental_id, user, lock=True)
    operation = db.scalar(
        select(OperationRequest)
        .where(OperationRequest.id == operation_id)
        .with_for_update()
    )
    if operation.status != "pending":
        raise HTTPException(409, "This request has already been resolved")
    if status == "completed":
        require_active(rental)
        rental.power = "stopped" if operation.kind == "stop" else "running"
    operation.status = status
    operation.result = result
    operation.resolved_by = user.id
    operation.resolved_at = now()
    record(db, user, "operation_resolved", "operation", operation.id, status)
    db.flush()
    return operation


def flag_expired(db: Session) -> int:
    candidates = db.scalars(
        select(Rental.id).where(
            Rental.status == "active", Rental.expires_at <= now()
        )
    ).all()
    count = 0
    for rental_id in candidates:
        snapshot = db.get(Rental, rental_id)
        order = db.scalar(
            select(Order)
            .where(Order.id == snapshot.order_id)
            .with_for_update(skip_locked=True)
        )
        if not order:
            continue
        rental = db.scalar(
            select(Rental)
            .where(Rental.id == rental_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if rental.status != "active" or rental.expires_at > now():
            continue
        rental.status = "suspension_pending"
        order.status = "expired"
        record(
            db,
            None,
            "rental_expired",
            "rental",
            rental.id,
            "Waiting for suspension",
        )
        count += 1
    db.flush()
    return count

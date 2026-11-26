from collections import defaultdict
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.billing.presenters import payment_view
from app.config import get_settings
from app.models import (
    Invoice,
    OperationRequest,
    Order,
    Payment,
    Plan,
    Rental,
    Server,
)


def plan_view(plan: Plan) -> dict:
    return {
        "id": plan.id,
        "name": plan.name,
        "description": plan.description,
        "cpu": plan.cpu,
        "ram_gb": plan.ram_gb,
        "disk_gb": plan.disk_gb,
        "monthly_cents": plan.monthly_cents,
        "annual_cents": plan.annual_cents,
        "enabled": plan.enabled,
    }


def invoice_view(invoice: Invoice, payment: Payment | None = None) -> dict:
    return {
        "id": invoice.id,
        "number": f"INV-{invoice.id:04d}",
        "order_id": invoice.order_id,
        "rental_id": invoice.rental_id,
        "kind": invoice.kind,
        "amount_cents": invoice.amount_cents,
        "currency": invoice.currency,
        "status": invoice.status,
        "created_at": invoice.created_at,
        "paid_at": invoice.paid_at,
        "payment": payment_view(payment),
    }


def operation_view(operation: OperationRequest) -> dict:
    return {
        "id": operation.id,
        "rental_id": operation.rental_id,
        "kind": operation.kind,
        "status": operation.status,
        "result": operation.result,
        "created_at": operation.created_at,
        "resolved_at": operation.resolved_at,
    }


def rental_view(db: Session, rental: Rental) -> dict:
    server = db.get(Server, rental.server_id)
    order = db.get(Order, rental.order_id)
    operations = db.scalars(
        select(OperationRequest)
        .where(OperationRequest.rental_id == rental.id)
        .order_by(OperationRequest.id.desc())
    ).all()
    return {
        "id": rental.id,
        "order_id": order.id,
        "server_id": server.id,
        "name": server.name,
        "address": str(server.address),
        "ssh_user": server.ssh_user,
        "plan_name": order.plan_name,
        "cpu": order.cpu,
        "ram_gb": order.ram_gb,
        "disk_gb": order.disk_gb,
        "term": order.term,
        "renewal_cents": order.renewal_cents,
        "started_at": rental.started_at,
        "expires_at": rental.expires_at,
        "status": rental.status,
        "power": rental.power,
        "auto_renew_card_id": rental.auto_renew_card_id,
        # First automatic charge attempt; earlier when already in window.
        "auto_renew_at": (
            rental.expires_at
            - timedelta(days=get_settings().auto_renew_days_before)
            if rental.auto_renew_card_id
            else None
        ),
        "operations": [operation_view(item) for item in operations],
    }


def order_views(db: Session, orders: list[Order]) -> list[dict]:
    """Present a page of orders with three queries in total."""
    if not orders:
        return []
    ids = [order.id for order in orders]
    invoices = defaultdict(list)
    for invoice in db.scalars(
        select(Invoice).where(Invoice.order_id.in_(ids)).order_by(Invoice.id)
    ):
        invoices[invoice.order_id].append(invoice)
    invoice_ids = [item.id for items in invoices.values() for item in items]
    latest = {}
    for payment in db.scalars(
        select(Payment)
        .where(Payment.invoice_id.in_(invoice_ids))
        .order_by(Payment.id)
    ):
        latest[payment.invoice_id] = payment
    rentals = dict(
        db.execute(
            select(Rental.order_id, Rental.id).where(Rental.order_id.in_(ids))
        ).all()
    )
    return [
        {
            "id": order.id,
            "plan_name": order.plan_name,
            "cpu": order.cpu,
            "ram_gb": order.ram_gb,
            "disk_gb": order.disk_gb,
            "price_cents": order.price_cents,
            "renewal_cents": order.renewal_cents,
            "term": order.term,
            "status": order.status,
            "created_at": order.created_at,
            "invoices": [
                invoice_view(item, latest.get(item.id))
                for item in invoices[order.id]
            ],
            "rental_id": rentals.get(order.id),
        }
        for order in orders
    ]


def order_view(db: Session, order: Order) -> dict:
    return order_views(db, [order])[0]

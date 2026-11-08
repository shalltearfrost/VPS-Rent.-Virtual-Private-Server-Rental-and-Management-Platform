from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Invoice, OperationRequest, Order, Plan, Rental, Server


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


def invoice_view(invoice: Invoice) -> dict:
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
        "operations": [operation_view(item) for item in operations],
    }


def order_view(db: Session, order: Order) -> dict:
    invoices = db.scalars(
        select(Invoice)
        .where(Invoice.order_id == order.id)
        .order_by(Invoice.id)
    ).all()
    rental = db.scalar(select(Rental).where(Rental.order_id == order.id))
    return {
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
        "invoices": [invoice_view(item) for item in invoices],
        "rental_id": rental.id if rental else None,
    }

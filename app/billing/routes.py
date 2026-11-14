"""Payment, renewal and saved-card endpoints."""

import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.billing.monobank import (
    Monobank,
    MonobankError,
    get_gateway,
    optional_gateway,
)
from app.billing.presenters import card_view, payment_view
from app.billing.schemas import AutoRenewInput, PaymentInput
from app.billing.service import (
    customer_renewal_invoice,
    handle_webhook,
    refresh_invoice,
    remove_card,
    set_auto_renew,
    start_payment,
)
from app.models import Order, PaymentCard
from app.presenters import invoice_view, rental_view
from app.security import Customer, Db
from app.services import owned_rental

router = APIRouter(prefix="/api", tags=["billing"])
Gateway = Annotated[Monobank, Depends(get_gateway)]
OptionalGateway = Annotated[Monobank | None, Depends(optional_gateway)]


@router.get("/invoices/{invoice_id}")
def invoice_details(
    invoice_id: int, user: Customer, db: Db, gateway: OptionalGateway
):
    """Invoice with its latest payment; a pending payment is re-checked."""
    invoice, payment = refresh_invoice(db, gateway, user, invoice_id)
    order = db.get(Order, invoice.order_id)
    return {
        **invoice_view(invoice, payment),
        "plan_name": order.plan_name,
        "term": order.term,
    }


@router.post("/invoices/{invoice_id}/payments", status_code=201)
def pay(
    invoice_id: int,
    data: PaymentInput,
    user: Customer,
    db: Db,
    gateway: Gateway,
):
    """Open a Monobank payment page; the client redirects to page_url."""
    return payment_view(start_payment(db, gateway, user, invoice_id, data))


@router.post("/payments/monobank/webhook", include_in_schema=False)
async def monobank_webhook(request: Request, gateway: Gateway, db: Db):
    """Signed status callback. Polling covers missed or local webhooks."""
    body = await request.body()
    signature = request.headers.get("x-sign", "")
    try:
        valid = await run_in_threadpool(
            gateway.verify_webhook, body, signature
        )
    except MonobankError as error:
        raise HTTPException(503, "Signature key unavailable") from error
    if not valid:
        raise HTTPException(400, "Invalid signature")
    try:
        data = json.loads(body)
        data["invoiceId"], data["status"]
    except (ValueError, KeyError, TypeError) as error:
        raise HTTPException(400, "Malformed webhook") from error
    await run_in_threadpool(handle_webhook, db, gateway, data)
    return {"status": "ok"}


@router.get("/cards")
def cards(user: Customer, db: Db):
    return [
        card_view(card)
        for card in db.scalars(
            select(PaymentCard)
            .where(
                PaymentCard.customer_id == user.id,
                PaymentCard.removed_at.is_(None),
            )
            .order_by(PaymentCard.id)
        )
    ]


@router.delete("/cards/{card_id}", status_code=204)
def delete_card(
    card_id: int, user: Customer, db: Db, gateway: OptionalGateway
):
    remove_card(db, gateway, user, card_id)


@router.post("/rentals/{rental_id}/renewal-invoice")
def renew(rental_id: int, user: Customer, db: Db):
    return invoice_view(customer_renewal_invoice(db, user, rental_id))


@router.put("/rentals/{rental_id}/auto-renew")
def auto_renewal(rental_id: int, data: AutoRenewInput, user: Customer, db: Db):
    rental, _ = owned_rental(db, rental_id, user, lock=True)
    set_auto_renew(db, rental, user, data.card_id)
    return rental_view(db, rental)

"""Review-only regression probes; no real Monobank requests are made."""

import json
from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.billing.service import run_billing_cycle
from app.main import app
from app.models import Invoice, Payment
from app.security import now
from tests.conftest import pay
from tests.test_payments import (
    enable_auto_renew,
    move_expiry,
    renewal_invoice,
)


def replace_transport(monobank, handler):
    monobank.gateway.http.close()
    monobank.gateway.http = httpx.Client(
        base_url="https://mono.test",
        headers={"X-Token": "test-token"},
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"amount": 1},
        {"ccy": 980},
        {"finalAmount": 1},
    ],
)
def test_signed_wrong_amount_or_currency_is_not_fulfilled(
    clients, inventory, monobank, changes, db
):
    customer = clients["customer"]
    order = customer.post(
        "/api/orders",
        json={
            "plan_id": inventory[0].id,
            "term": "monthly",
        },
    ).json()
    invoice_id = order["invoices"][0]["id"]
    started = customer.post(
        f"/api/invoices/{invoice_id}/payments",
        json={
            "idempotency_key": "review-mismatched-money",
        },
    )
    assert started.status_code == 201
    event = monobank.finish()
    event.update(changes)
    body = json.dumps(event).encode()
    with TestClient(app) as bank:
        response = bank.post(
            "/api/payments/monobank/webhook",
            content=body,
            headers={
                "x-sign": monobank.sign(body),
                "content-type": "application/json",
            },
        )
    assert response.status_code == 409
    db.expire_all()
    assert db.get(Invoice, invoice_id).status == "unpaid"
    monobank.invoices[monobank.last_invoice_id].update(changes)
    assert customer.get(f"/api/invoices/{invoice_id}").status_code == 409
    db.expire_all()
    assert db.get(Invoice, invoice_id).status == "unpaid"


def test_processing_refund_is_not_reported_as_completed(
    clients, active_rental, monobank, db, test_database
):
    customer = clients["customer"]
    rental_id = active_rental["id"]
    invoice = renewal_invoice(customer, rental_id)
    pay(customer, monobank, invoice["id"], status="pending")
    move_expiry(db, rental_id, timedelta(seconds=-5))
    clients["operator"].post("/api/operator/expiry-scan")
    monobank.finish(at=now())

    def handler(request):
        if request.url.path == "/api/merchant/invoice/cancel":
            return httpx.Response(200, json={"status": "processing"})
        return monobank.handle(request)

    replace_transport(monobank, handler)
    customer.get(f"/api/invoices/{invoice['id']}")
    run_billing_cycle(test_database, monobank.gateway)
    result = customer.get(f"/api/invoices/{invoice['id']}").json()
    assert result["payment"]["status"] != "refunded", result


def test_response_timeout_does_not_charge_the_same_renewal_again(
    clients, active_rental, monobank, db, test_database
):
    customer = clients["customer"]
    rental_id = active_rental["id"]
    enable_auto_renew(customer, monobank, rental_id)
    move_expiry(db, rental_id, timedelta(days=2))
    lost = False

    def handler(request):
        nonlocal lost
        response = monobank.handle(request)
        if request.url.path == "/api/merchant/wallet/payment" and not lost:
            lost = True
            raise httpx.ReadTimeout(
                "Response lost after bank success", request=request
            )
        return response

    replace_transport(monobank, handler)
    run_billing_cycle(test_database, monobank.gateway)
    db.expire_all()
    first = db.scalar(select(Payment).where(Payment.initiated_by == "auto"))
    assert first.status == "uncertain" and first.provider_invoice_id is None
    assert first.review_required
    first.created_at = now() - timedelta(hours=13)
    db.commit()
    run_billing_cycle(test_database, monobank.gateway)
    charges = [
        body
        for _, path, body in monobank.requests
        if path == "/api/merchant/wallet/payment"
    ]
    assert len(charges) == 1, {
        "bank_charges": len(charges),
        "references": [
            body["merchantPaymInfo"]["reference"] for body in charges
        ],
    }

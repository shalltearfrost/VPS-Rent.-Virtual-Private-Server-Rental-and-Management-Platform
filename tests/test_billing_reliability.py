import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.billing.service import (
    auto_renew,
    dispatch_charge,
    run_billing_cycle,
)
from app.main import app
from app.models import Activity, Invoice, Payment, Rental
from app.security import now
from tests.conftest import pay
from tests.test_payments import (
    enable_auto_renew,
    move_expiry,
    renewal_invoice,
)
from tests.test_review_findings import replace_transport


def notify(monobank, event):
    body = json.dumps(event).encode()
    with TestClient(app) as bank:
        return bank.post(
            "/api/payments/monobank/webhook",
            content=body,
            headers={"x-sign": monobank.sign(body)},
        )


def test_unknown_charge_recovers_from_signed_reference(
    clients, active_rental, monobank, db, test_database
):
    rental_id = active_rental["id"]
    enable_auto_renew(clients["customer"], monobank, rental_id)
    expires = move_expiry(db, rental_id, timedelta(days=2))

    def lose_response(request):
        response = monobank.handle(request)
        if request.url.path == "/api/merchant/wallet/payment":
            raise httpx.ReadTimeout("Lost after acceptance", request=request)
        return response

    replace_transport(monobank, lose_response)
    run_billing_cycle(test_database, monobank.gateway)
    db.expire_all()
    attempt = db.scalar(select(Payment).where(Payment.initiated_by == "auto"))
    assert attempt.status == "uncertain"
    assert attempt.provider_invoice_id is None
    event = monobank.public(monobank.invoices[monobank.last_invoice_id])
    assert notify(monobank, event).status_code == 200
    assert notify(monobank, event).status_code == 200
    db.expire_all()
    assert db.get(Payment, attempt.id).status == "succeeded"
    assert not db.get(Payment, attempt.id).review_required
    assert db.get(Rental, rental_id).expires_at == expires + timedelta(days=30)


def test_crash_after_durable_marker_does_not_retry(
    clients, active_rental, monobank, db, test_database, monkeypatch
):
    rental_id = active_rental["id"]
    enable_auto_renew(clients["customer"], monobank, rental_id)
    move_expiry(db, rental_id, timedelta(days=2))

    def crash(**arguments):
        raise RuntimeError("Simulated worker crash")

    with monkeypatch.context() as context:
        context.setattr(monobank.gateway, "charge_card", crash)
        run_billing_cycle(test_database, monobank.gateway)
    run_billing_cycle(test_database, monobank.gateway)
    db.expire_all()
    attempt = db.scalar(select(Payment).where(Payment.initiated_by == "auto"))
    assert attempt.status == "uncertain"
    assert attempt.review_required
    assert not any(
        path == "/api/merchant/wallet/payment"
        for _, path, _ in monobank.requests
    )


def test_two_dispatchers_send_one_charge(
    clients, active_rental, monobank, db, test_database
):
    rental_id = active_rental["id"]
    enable_auto_renew(clients["customer"], monobank, rental_id)
    move_expiry(db, rental_id, timedelta(days=2))
    with db.begin():
        assert auto_renew(db, monobank.gateway, rental_id) == "reserved"
    payment_id = db.scalar(
        select(Payment.id).where(Payment.status == "reserved")
    )
    barrier = Barrier(2)

    def dispatch(_):
        barrier.wait(timeout=10)
        dispatch_charge(test_database, monobank.gateway, payment_id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(dispatch, range(2)))
    charges = [
        body
        for _, path, body in monobank.requests
        if path == "/api/merchant/wallet/payment"
    ]
    assert len(charges) == 1


@pytest.mark.parametrize("refund_status", ["processing", "failure"])
def test_refund_waits_for_matching_confirmation(
    clients, active_rental, monobank, db, test_database, refund_status
):
    customer = clients["customer"]
    rental_id = active_rental["id"]
    invoice = renewal_invoice(customer, rental_id)
    pay(customer, monobank, invoice["id"], status="pending")
    move_expiry(db, rental_id, timedelta(seconds=-5))
    monobank.finish(at=now())
    monobank.refund_status = refund_status
    assert customer.get(f"/api/invoices/{invoice['id']}").status_code == 200
    run_billing_cycle(test_database, monobank.gateway)
    run_billing_cycle(test_database, monobank.gateway)
    db.expire_all()
    attempt = db.scalar(
        select(Payment).where(Payment.invoice_id == invoice["id"])
    )
    assert attempt.status == "refund_pending"
    assert attempt.review_required == (refund_status == "failure")
    assert len(monobank.refunds) == 1
    bank_invoice = monobank.invoices[attempt.provider_invoice_id]
    bank_invoice["cancelList"][0]["status"] = "success"
    bank_invoice["modifiedDate"] = now().isoformat()
    event = monobank.public(bank_invoice)
    assert notify(monobank, event).status_code == 200
    assert notify(monobank, event).status_code == 200
    db.expire_all()
    assert db.get(Payment, attempt.id).status == "refunded"
    assert not db.get(Payment, attempt.id).review_required
    assert db.get(Invoice, invoice["id"]).status == "unpaid"
    assert (
        db.scalar(
            select(func.count())
            .select_from(Activity)
            .where(
                Activity.entity_type == "invoice",
                Activity.entity_id == invoice["id"],
                Activity.action == "payment_refunded",
            )
        )
        == 1
    )


def test_live_merchant_is_rejected_before_invoice_creation(
    clients, inventory, monobank
):
    def live_merchant(request):
        if request.url.path == "/api/merchant/details":
            return httpx.Response(200, json={"merchantId": "live_merchant"})
        return monobank.handle(request)

    replace_transport(monobank, live_merchant)
    customer = clients["customer"]
    order = customer.post(
        "/api/orders",
        json={"plan_id": inventory[0].id, "term": "monthly"},
    ).json()
    response = customer.post(
        f"/api/invoices/{order['invoices'][0]['id']}/payments",
        json={"idempotency_key": "reject-live-merchant"},
    )
    assert response.status_code == 502
    assert not monobank.invoices


def test_oversized_webhook_is_rejected(monobank):
    with TestClient(app) as bank:
        response = bank.post(
            "/api/payments/monobank/webhook", content=b"x" * 65_000
        )
    assert response.status_code == 413

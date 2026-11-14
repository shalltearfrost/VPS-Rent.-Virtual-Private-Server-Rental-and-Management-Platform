import json
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.billing.monobank import optional_gateway
from app.billing.service import run_billing_cycle
from app.main import app
from app.models import Activity, Invoice, Order, Payment, PaymentCard, Rental
from app.security import now
from tests.conftest import PASSWORD, pay

WEBHOOK = "/api/payments/monobank/webhook"


def renewal_invoice(customer, rental_id):
    response = customer.post(f"/api/rentals/{rental_id}/renewal-invoice")
    assert response.status_code == 200, response.text
    return response.json()


def move_expiry(db, rental_id, delta):
    rental = db.get(Rental, rental_id)
    rental.started_at = now() - timedelta(days=30)
    rental.expires_at = now() + delta
    db.commit()
    return rental.expires_at


def test_initial_payment_is_charged_in_euro(clients, inventory, monobank):
    customer = clients["customer"]
    order = customer.post(
        "/api/orders", json={"plan_id": inventory[0].id, "term": "monthly"}
    ).json()
    invoice_id = order["invoices"][0]["id"]
    started = customer.post(
        f"/api/invoices/{invoice_id}/payments",
        json={"idempotency_key": "first-attempt-key"},
    )
    assert started.status_code == 201, started.text
    payment = started.json()
    assert payment["status"] == "pending"
    assert payment["page_url"].startswith("https://pay.mbnk.test/")
    sent = next(
        body
        for method, path, body in monobank.requests
        if path == "/api/merchant/invoice/create"
    )
    # Invoice amount in euro cents, ISO 4217 code 978 (EUR), no conversion.
    assert sent["amount"] == 169 and sent["ccy"] == 978
    assert sent["redirectUrl"].endswith(f"/#invoice/{invoice_id}")
    assert "webHookUrl" not in sent  # PUBLIC_URL is plain http locally
    assert "saveCardData" not in sent
    # A second click reuses the open bank page instead of a new invoice.
    again = customer.post(
        f"/api/invoices/{invoice_id}/payments",
        json={"idempotency_key": "second-attempt-key"},
    )
    assert again.json()["id"] == payment["id"]
    pending = customer.get(f"/api/invoices/{invoice_id}").json()
    assert pending["status"] == "unpaid"
    assert pending["payment"]["status"] == "pending"
    monobank.finish()
    paid = customer.get(f"/api/invoices/{invoice_id}").json()
    assert paid["status"] == "paid" and paid["payment"]["page_url"] is None
    assert (
        customer.get(f"/api/orders/{order['id']}").json()["status"]
        == "awaiting_allocation"
    )


def test_payments_need_a_configured_token(clients, inventory):
    app.dependency_overrides[optional_gateway] = lambda: None
    customer = clients["customer"]
    order = customer.post(
        "/api/orders", json={"plan_id": inventory[0].id, "term": "monthly"}
    ).json()
    response = customer.post(
        f"/api/invoices/{order['invoices'][0]['id']}/payments",
        json={"idempotency_key": "no-token-payment"},
    )
    assert response.status_code == 503
    assert "MONOBANK_TOKEN" in response.json()["detail"]


def test_bank_errors_do_not_create_payments(clients, inventory, monobank, db):
    monobank.create_error = "Invalid merchant"
    customer = clients["customer"]
    order = customer.post(
        "/api/orders", json={"plan_id": inventory[0].id, "term": "monthly"}
    ).json()
    response = customer.post(
        f"/api/invoices/{order['invoices'][0]['id']}/payments",
        json={"idempotency_key": "bank-rejected-key"},
    )
    assert response.status_code == 502
    assert response.json()["detail"] == "Invalid merchant"
    assert db.scalar(select(Payment)) is None


def test_signed_webhook_and_out_of_order_delivery(
    clients, inventory, monobank, db
):
    customer = clients["customer"]
    order = customer.post(
        "/api/orders", json={"plan_id": inventory[0].id, "term": "monthly"}
    ).json()
    invoice_id = order["invoices"][0]["id"]
    customer.post(
        f"/api/invoices/{invoice_id}/payments",
        json={"idempotency_key": "webhook-payment-key"},
    )
    processing = monobank.finish(status="processing")
    success = monobank.finish(status="success")
    hook = TestClient(app)
    body = json.dumps(success).encode()
    forged = hook.post(WEBHOOK, content=body, headers={"x-sign": "AAAA"})
    assert forged.status_code == 400
    assert (
        hook.post(
            WEBHOOK,
            content=body,
            headers={"x-sign": monobank.sign(body + b" ")},
        ).status_code
        == 400
    )
    assert (
        hook.post(
            WEBHOOK, content=body, headers={"x-sign": monobank.sign(body)}
        ).status_code
        == 200
    )
    # The older "processing" event arrives last and must be ignored.
    late = json.dumps(processing).encode()
    assert (
        hook.post(
            WEBHOOK, content=late, headers={"x-sign": monobank.sign(late)}
        ).status_code
        == 200
    )
    db.expire_all()
    assert db.get(Invoice, invoice_id).status == "paid"
    assert db.scalar(select(Payment.status)) == "succeeded"
    unknown = json.dumps({"invoiceId": "other", "status": "success"}).encode()
    assert (
        hook.post(
            WEBHOOK,
            content=unknown,
            headers={"x-sign": monobank.sign(unknown)},
        ).status_code
        == 200
    )
    hook.close()


def test_saved_card_enables_auto_renewal(clients, active_rental, monobank, db):
    customer = clients["customer"]
    rental_id = active_rental["id"]
    original = db.get(Rental, rental_id).expires_at
    invoice = renewal_invoice(customer, rental_id)
    paid = pay(customer, monobank, invoice["id"], save_card=True)
    assert paid.json()["status"] == "paid"
    sent = [
        body
        for method, path, body in monobank.requests
        if path == "/api/merchant/invoice/create"
    ][-1]
    customer_id = db.get(Order, active_rental["order_id"]).customer_id
    assert sent["saveCardData"] == {
        "saveCard": True,
        "walletId": f"vpsrent-{customer_id}",
    }
    db.expire_all()
    rental = db.get(Rental, rental_id)
    assert rental.expires_at == original + timedelta(days=30)
    card = db.get(PaymentCard, rental.auto_renew_card_id)
    assert card.masked_pan == "444403******1902"
    assert "card-token" not in card.token_ciphertext
    cards = customer.get("/api/cards").json()
    assert [item["masked_pan"] for item in cards] == [card.masked_pan]
    assert "token" not in str(cards)
    details = customer.get(f"/api/rentals/{rental_id}").json()
    assert details["auto_renew_card_id"] == card.id


def test_initial_saved_card_is_used_after_allocation(
    clients, inventory, monobank
):
    plan, server = inventory
    customer = clients["customer"]
    order = customer.post(
        "/api/orders", json={"plan_id": plan.id, "term": "monthly"}
    ).json()
    pay(customer, monobank, order["invoices"][0]["id"], save_card=True)
    rental = clients["operator"].post(
        f"/api/operator/orders/{order['id']}/allocate",
        json={"server_id": server.id},
    )
    assert rental.json()["auto_renew_card_id"] is not None


def enable_auto_renew(customer, monobank, rental_id):
    order_id = customer.get(f"/api/rentals/{rental_id}").json()["order_id"]
    # Save a card with the renewal payment, then reset the term window.
    invoice = renewal_invoice(customer, rental_id)
    pay(customer, monobank, invoice["id"], save_card=True)
    return order_id


def test_auto_renewal_charges_saved_card_once(
    clients, active_rental, monobank, db, test_database
):
    customer = clients["customer"]
    rental_id = active_rental["id"]
    enable_auto_renew(customer, monobank, rental_id)
    expires = move_expiry(db, rental_id, timedelta(days=10))
    run_billing_cycle(test_database, monobank.gateway)
    assert not any(
        path == "/api/merchant/wallet/payment"
        for _, path, _ in monobank.requests
    )
    expires = move_expiry(db, rental_id, timedelta(days=2))
    run_billing_cycle(test_database, monobank.gateway)
    run_billing_cycle(test_database, monobank.gateway)
    charges = [
        body
        for _, path, body in monobank.requests
        if path == "/api/merchant/wallet/payment"
    ]
    assert len(charges) == 1
    assert charges[0]["initiationKind"] == "merchant"
    assert charges[0]["cardToken"].startswith("card-token-")
    assert charges[0]["amount"] == 169 and charges[0]["ccy"] == 978
    db.expire_all()
    assert db.get(Rental, rental_id).expires_at == expires + timedelta(days=30)
    auto = db.scalar(select(Payment).where(Payment.initiated_by == "auto"))
    assert auto.status == "succeeded"


def test_failed_auto_renewal_waits_before_retry(
    clients, active_rental, monobank, db, test_database
):
    customer = clients["customer"]
    rental_id = active_rental["id"]
    enable_auto_renew(customer, monobank, rental_id)
    expires = move_expiry(db, rental_id, timedelta(days=2))
    monobank.charge_status = "failure"
    run_billing_cycle(test_database, monobank.gateway)
    monobank.charge_error = "Token expired"
    run_billing_cycle(test_database, monobank.gateway)
    db.expire_all()
    attempts = db.scalars(
        select(Payment).where(Payment.initiated_by == "auto")
    ).all()
    assert [item.status for item in attempts] == ["failed"]
    assert db.get(Rental, rental_id).expires_at == expires
    # After the retry interval the next attempt is made.
    attempts[0].created_at = now() - timedelta(hours=13)
    db.commit()
    run_billing_cycle(test_database, monobank.gateway)
    db.expire_all()
    statuses = db.scalars(
        select(Payment.failure_reason)
        .where(Payment.initiated_by == "auto")
        .order_by(Payment.id)
    ).all()
    assert statuses == ["Card declined", "Token expired"]
    assert db.scalar(
        select(Activity).where(Activity.action == "auto_renewal_failed")
    )


def test_expired_rental_is_never_auto_renewed(
    clients, active_rental, monobank, db, test_database
):
    customer = clients["customer"]
    rental_id = active_rental["id"]
    enable_auto_renew(customer, monobank, rental_id)
    move_expiry(db, rental_id, timedelta(seconds=-1))
    run_billing_cycle(test_database, monobank.gateway)
    assert not any(
        path == "/api/merchant/wallet/payment"
        for _, path, _ in monobank.requests
    )


def test_late_success_after_expiry_is_refunded(
    clients, active_rental, monobank, db
):
    customer = clients["customer"]
    rental_id = active_rental["id"]
    invoice = renewal_invoice(customer, rental_id)
    pay(customer, monobank, invoice["id"], status="pending")
    expired_at = move_expiry(db, rental_id, timedelta(seconds=-5))
    clients["operator"].post("/api/operator/expiry-scan")
    monobank.finish(at=now())
    result = customer.get(f"/api/invoices/{invoice['id']}").json()
    assert result["status"] == "unpaid"
    assert result["payment"]["status"] == "refunded"
    assert monobank.refunds == [monobank.last_invoice_id]
    db.expire_all()
    rental = db.get(Rental, rental_id)
    assert rental.expires_at == expired_at
    assert rental.status == "suspension_pending"


def test_success_completed_before_expiry_restores_rental(
    clients, active_rental, monobank, db
):
    customer = clients["customer"]
    rental_id = active_rental["id"]
    invoice = renewal_invoice(customer, rental_id)
    pay(customer, monobank, invoice["id"], status="pending")
    expired_at = move_expiry(db, rental_id, timedelta(seconds=-5))
    clients["operator"].post("/api/operator/expiry-scan")
    # The bank confirmed the payment before expiry; we learn about it later.
    monobank.finish(at=expired_at - timedelta(minutes=1))
    result = customer.get(f"/api/invoices/{invoice['id']}").json()
    assert result["status"] == "paid"
    db.expire_all()
    rental = db.get(Rental, rental_id)
    assert rental.status == "active"
    assert rental.expires_at == expired_at + timedelta(days=30)
    assert db.get(Order, rental.order_id).status == "active"


def test_card_management_is_private(clients, active_rental, monobank, db):
    customer = clients["customer"]
    rental_id = active_rental["id"]
    enable_auto_renew(customer, monobank, rental_id)
    card_id = customer.get("/api/cards").json()[0]["id"]
    other = TestClient(app)
    session = other.post(
        "/api/auth/register",
        json={"email": "other@example.com", "password": PASSWORD},
    ).json()
    other.headers["X-CSRF-Token"] = session["csrf_token"]
    assert other.get("/api/cards").json() == []
    assert other.delete(f"/api/cards/{card_id}").status_code == 404
    assert (
        other.put(
            f"/api/rentals/{rental_id}/auto-renew", json={"card_id": card_id}
        ).status_code
        == 404
    )
    other.close()
    path = f"/api/rentals/{rental_id}/auto-renew"
    assert (
        customer.put(path, json={"card_id": None}).json()["auto_renew_card_id"]
        is None
    )
    assert (
        customer.put(path, json={"card_id": card_id}).json()[
            "auto_renew_card_id"
        ]
        == card_id
    )
    assert customer.delete(f"/api/cards/{card_id}").status_code == 204
    assert monobank.deleted_cards and customer.get("/api/cards").json() == []
    db.expire_all()
    assert db.get(Rental, rental_id).auto_renew_card_id is None
    assert customer.put(path, json={"card_id": card_id}).status_code == 404

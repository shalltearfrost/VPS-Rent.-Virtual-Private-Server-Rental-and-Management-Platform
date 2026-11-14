from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models import Activity, Order, Rental, Server
from app.security import now
from tests.conftest import PASSWORD, pay


def test_annual_allocation_uses_calendar_year(
    clients, inventory, db, monobank
):
    plan, server = inventory
    customer, operator = clients["customer"], clients["operator"]
    order = customer.post(
        "/api/orders",
        json={
            "plan_id": plan.id,
            "term": "annual",
        },
    ).json()
    assert order["price_cents"] == 1725
    paid = pay(customer, monobank, order["invoices"][0]["id"])
    assert paid.json()["status"] == "paid"
    response = operator.post(
        f"/api/operator/orders/{order['id']}/allocate",
        json={"server_id": server.id},
    )
    assert response.status_code == 201
    rental = db.get(Rental, response.json()["id"])
    assert rental.expires_at.year == rental.started_at.year + 1
    assert rental.expires_at.month == rental.started_at.month


def test_mismatched_server_stays_available(clients, paid_order, db):
    order, server = paid_order
    stored = db.get(Server, server.id)
    stored.ram_gb = 4
    db.commit()
    response = clients["operator"].post(
        f"/api/operator/orders/{order['id']}/allocate",
        json={"server_id": server.id},
    )
    assert response.status_code == 409
    db.expire_all()
    assert db.get(Server, server.id).state == "available"
    assert db.get(Order, order["id"]).status == "awaiting_allocation"


def test_existing_renewal_invoice_cannot_be_paid_after_expiry(
    clients, active_rental, db, monobank
):
    customer = clients["customer"]
    invoice = customer.post(
        f"/api/rentals/{active_rental['id']}/renewal-invoice"
    ).json()
    rental = db.get(Rental, active_rental["id"])
    rental.started_at = now() - timedelta(days=31)
    rental.expires_at = now() - timedelta(seconds=1)
    expired_at = rental.expires_at
    db.commit()
    assert pay(customer, monobank, invoice["id"]).status_code == 409
    db.expire_all()
    assert db.get(Rental, rental.id).expires_at == expired_at


def test_foreign_ticket_and_credential_audit(clients, active_rental, db):
    customer = clients["customer"]
    ticket = customer.post(
        "/api/tickets",
        json={
            "subject": "Private ticket",
            "body": "Private conversation",
            "rental_id": active_rental["id"],
        },
    ).json()
    with TestClient(app) as other:
        session = other.post(
            "/api/auth/register",
            json={
                "email": "third@example.com",
                "password": PASSWORD,
            },
        ).json()
        other.headers["X-CSRF-Token"] = session["csrf_token"]
        path = f"/api/tickets/{ticket['id']}"
        assert other.get(path).status_code == 404
        assert (
            other.post(
                f"{path}/messages", json={"body": "Unauthorized message"}
            ).status_code
            == 404
        )
    assert (
        customer.post(
            f"/api/rentals/{active_rental['id']}/reveal-password"
        ).status_code
        == 200
    )
    activities = db.scalars(select(Activity)).all()
    assert any(item.action == "password_viewed" for item in activities)
    assert all(PASSWORD not in item.result for item in activities)


def test_account_password_whitespace_is_preserved():
    with TestClient(app) as client:
        password = "  account-password-2026!  "
        data = {"email": "spaces@example.com", "password": password}
        session = client.post("/api/auth/register", json=data)
        assert session.status_code == 201
        assert (
            client.post(
                "/api/auth/login", json={**data, "password": password.strip()}
            ).status_code
            == 401
        )
        assert client.post("/api/auth/login", json=data).status_code == 200


def test_health_and_frontend_headers():
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert (
            "script-src 'self'" in response.headers["content-security-policy"]
        )
        assert client.get("/assets/public-sans-400.ttf").status_code == 200
        assert client.get("/api/health").json()["status"] == "ok"

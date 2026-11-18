from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.main import app
from app.models import Activity, Order, Payment, Rental, Server
from app.security import now
from tests.conftest import PASSWORD, pay


def test_registration_rejects_staff_roles_and_revokes_session(inventory):
    with TestClient(app) as client:
        data = {"email": "new@example.com", "password": PASSWORD}
        assert (
            client.post(
                "/api/auth/register", json={**data, "role": "operator"}
            ).status_code
            == 422
        )
        response = client.post("/api/auth/register", json=data)
        assert response.status_code == 201
        assert response.json()["user"]["role"] == "customer"
        csrf = response.json()["csrf_token"]
        assert (
            client.post(
                "/api/orders",
                json={"plan_id": inventory[0].id, "term": "monthly"},
            ).status_code
            == 403
        )
        client.headers["X-CSRF-Token"] = csrf
        assert client.post("/api/auth/logout").status_code == 204
        assert client.get("/api/auth/me").status_code == 401
        assert (
            client.post(
                "/api/auth/register", json={**data, "email": "NEW@example.com"}
            ).status_code
            == 409
        )
        assert (
            client.post(
                "/api/auth/login",
                json=data,
                headers={"Origin": "https://untrusted.example"},
            ).status_code
            == 403
        )


def test_real_product_flow(clients, inventory, db, monobank):
    customer, operator = clients["customer"], clients["operator"]
    plan, server = inventory
    assert customer.get("/").status_code == 200
    assert customer.get("/assets/app.js").status_code == 200
    assert customer.get("/api/health").json()["database"] == "postgresql"
    assert customer.get("/api/plans").json()[0]["name"] == "Starter"
    order = customer.post(
        "/api/orders",
        json={
            "plan_id": plan.id,
            "term": "monthly",
        },
    ).json()
    invoice = order["invoices"][0]
    assert order["status"] == "awaiting_payment"
    failed = pay(customer, monobank, invoice["id"], "failure")
    assert failed.json()["payment"]["status"] == "failed"
    assert failed.json()["payment"]["failure_reason"] == "Card declined"
    assert (
        customer.get(f"/api/orders/{order['id']}").json()["status"]
        == "awaiting_payment"
    )
    assert (
        operator.post(
            f"/api/operator/orders/{order['id']}/allocate",
            json={"server_id": server.id},
        ).status_code
        == 409
    )
    result = pay(customer, monobank, invoice["id"], key="successful-key-01")
    assert result.json()["status"] == "paid"
    duplicate = customer.post(
        f"/api/invoices/{invoice['id']}/payments",
        json={"idempotency_key": "successful-key-01"},
    )
    assert duplicate.json()["id"] == result.json()["payment"]["id"]
    assert operator.get("/api/operator/queue").json()[0]["id"] == order["id"]
    rental = operator.post(
        f"/api/operator/orders/{order['id']}/allocate",
        json={"server_id": server.id},
    ).json()
    stored = db.get(Rental, rental["id"])
    assert stored.expires_at - stored.started_at == timedelta(days=30)
    details = customer.get(f"/api/rentals/{rental['id']}").json()
    assert details["address"] == "192.0.2.1"
    assert "password" not in str(details)
    password = customer.post(f"/api/rentals/{rental['id']}/reveal-password")
    assert password.json()["password"] == PASSWORD
    assert password.headers["cache-control"] == "no-store"
    assert db.get(Server, server.id).password_ciphertext != PASSWORD
    assert db.scalar(select(func.count()).select_from(Activity)) >= 5


def test_operations_change_power_only_after_completion(clients, active_rental):
    customer, operator = clients["customer"], clients["operator"]
    rental_id = active_rental["id"]
    path = f"/api/rentals/{rental_id}"
    operation = customer.post(f"{path}/operations", json={"kind": "stop"})
    assert operation.status_code == 201
    assert customer.get(path).json()["power"] == "running"
    assert (
        customer.post(
            f"{path}/operations", json={"kind": "restart"}
        ).status_code
        == 409
    )
    resolve = f"/api/operator/operations/{operation.json()['id']}/resolve"
    assert (
        operator.post(
            resolve,
            json={
                "status": "completed",
                "result": "Stopped through provider panel",
            },
        ).status_code
        == 200
    )
    assert customer.get(path).json()["power"] == "stopped"
    assert (
        customer.post(
            f"{path}/operations", json={"kind": "restart"}
        ).status_code
        == 409
    )
    start = customer.post(f"{path}/operations", json={"kind": "start"}).json()
    operator.post(
        f"/api/operator/operations/{start['id']}/resolve",
        json={"status": "rejected", "result": "Maintenance in progress"},
    )
    assert customer.get(path).json()["power"] == "stopped"
    assert (
        operator.post(
            resolve, json={"status": "completed", "result": "Again"}
        ).status_code
        == 409
    )


def test_renewal_failed_duplicate_and_concurrent_payments(
    clients, active_rental, db, monobank
):
    customer = clients["customer"]
    rental_id = active_rental["id"]
    original = db.get(Rental, rental_id).expires_at
    invoice = customer.post(f"/api/rentals/{rental_id}/renewal-invoice").json()
    assert (
        customer.post(f"/api/rentals/{rental_id}/renewal-invoice").json()["id"]
        == invoice["id"]
    )
    failed = pay(customer, monobank, invoice["id"], "failure")
    assert failed.json()["status"] == "unpaid"
    db.expire_all()
    assert db.get(Rental, rental_id).expires_at == original
    path = f"/api/invoices/{invoice['id']}"

    def start(_):
        return customer.post(
            f"{path}/payments", json={"idempotency_key": str(uuid4())}
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        started = list(executor.map(start, range(4)))
    assert [response.status_code for response in started] == [201] * 4
    assert len({response.json()["id"] for response in started}) == 1
    monobank.finish()
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: customer.get(path), range(4)))
    assert {response.json()["status"] for response in results} == {"paid"}
    db.expire_all()
    assert db.get(Rental, rental_id).expires_at == original + timedelta(
        days=30
    )
    assert (
        db.scalar(
            select(func.count())
            .select_from(Payment)
            .where(
                Payment.invoice_id == invoice["id"],
                Payment.status == "succeeded",
            )
        )
        == 1
    )


def test_expiration_suspension_preparation(clients, active_rental, db):
    customer, operator = clients["customer"], clients["operator"]
    rental_id = active_rental["id"]
    rental = db.get(Rental, rental_id)
    rental.started_at = now() - timedelta(days=31)
    rental.expires_at = now() - timedelta(days=1)
    db.commit()
    assert operator.post("/api/operator/expiry-scan").json()["flagged"] == 1
    assert (
        customer.post(f"/api/rentals/{rental_id}/renewal-invoice").status_code
        == 409
    )
    assert (
        customer.post(f"/api/rentals/{rental_id}/reveal-password").status_code
        == 409
    )
    assert (
        operator.post(
            f"/api/operator/rentals/{rental_id}/prepare",
            json={"password": "Rotated-password-2026!"},
        ).status_code
        == 409
    )
    assert (
        operator.post(f"/api/operator/rentals/{rental_id}/suspend").status_code
        == 200
    )
    db.expire_all()
    assert db.get(Server, rental.server_id).state == "suspended"
    assert (
        operator.post(
            f"/api/operator/rentals/{rental_id}/prepare",
            json={"password": PASSWORD},
        ).status_code
        == 409
    )
    assert (
        operator.post(
            f"/api/operator/rentals/{rental_id}/prepare",
            json={"password": "Rotated-password-2026!"},
        ).status_code
        == 200
    )
    db.expire_all()
    assert db.get(Server, rental.server_id).state == "available"
    assert db.get(Rental, rental_id).status == "ended"


def test_customer_isolation_and_staff_permissions(
    clients, active_rental, monobank
):
    other = TestClient(app)
    session = other.post(
        "/api/auth/register",
        json={
            "email": "other@example.com",
            "password": PASSWORD,
        },
    ).json()
    other.headers["X-CSRF-Token"] = session["csrf_token"]
    order_id, rental_id = active_rental["order_id"], active_rental["id"]
    invoice_id = (
        clients["customer"]
        .get(f"/api/orders/{order_id}")
        .json()["invoices"][0]["id"]
    )
    for path in (
        f"/api/orders/{order_id}",
        f"/api/rentals/{rental_id}",
        f"/api/invoices/{invoice_id}",
    ):
        assert other.get(path).status_code == 404
    assert (
        other.post(f"/api/rentals/{rental_id}/reveal-password").status_code
        == 404
    )
    for role in ("support", "manager"):
        assert clients[role].get("/api/operator/servers").status_code == 403
    for role in ("operator", "support"):
        assert clients[role].get("/api/management/plans").status_code == 403
        assert pay(clients[role], monobank, invoice_id).status_code == 403
    other.close()


def test_plan_edits_preserve_order_snapshot(clients, inventory):
    customer, manager = clients["customer"], clients["manager"]
    plan = inventory[0]
    order = customer.post(
        "/api/orders",
        json={
            "plan_id": plan.id,
            "term": "monthly",
        },
    ).json()
    assert (
        manager.put(
            f"/api/management/plans/{plan.id}",
            json={
                "name": "Revised",
                "description": "New resources",
                "cpu": 8,
                "ram_gb": 16,
                "disk_gb": 250,
                "monthly_cents": 999,
                "annual_cents": 9999,
                "enabled": False,
            },
        ).status_code
        == 200
    )
    assert customer.get("/api/plans").json() == []
    saved = customer.get(f"/api/orders/{order['id']}").json()
    assert saved["plan_name"] == "Starter"
    assert saved["cpu"] == 1 and saved["price_cents"] == 169
    assert (
        customer.post(
            "/api/orders",
            json={
                "plan_id": plan.id,
                "term": "monthly",
            },
        ).status_code
        == 409
    )


def test_support_thread_privacy_and_history(clients, active_rental):
    customer, support = clients["customer"], clients["support"]
    ticket = customer.post(
        "/api/tickets",
        json={
            "subject": "Connection issue",
            "body": "Cannot connect",
            "rental_id": active_rental["id"],
        },
    ).json()
    assert clients["operator"].get("/api/tickets").status_code == 403
    assert clients["manager"].get("/api/tickets").status_code == 403
    path = f"/api/tickets/{ticket['id']}"
    assert support.get(path).json()["server"]["address"] == "192.0.2.1"
    assert (
        support.post(
            f"{path}/messages", json={"body": "Please check your SSH port"}
        ).status_code
        == 201
    )
    assert (
        support.post(
            f"{path}/status", json={"status": "in_progress"}
        ).status_code
        == 200
    )
    assert customer.get(path).json()["messages"][1]["author"] == "support"
    support.post(f"{path}/status", json={"status": "closed"})
    assert (
        customer.post(
            f"{path}/messages", json={"body": "Another message"}
        ).status_code
        == 409
    )
    assert all(
        item["entity_type"] == "ticket"
        for item in support.get("/api/activity").json()
    )


def test_server_cannot_be_allocated_twice(clients, paid_order, db, monobank):
    customer, operator = clients["customer"], clients["operator"]
    first, server = paid_order
    second = customer.post(
        "/api/orders",
        json={
            "plan_id": db.get(Order, first["id"]).plan_id,
            "term": "monthly",
        },
    ).json()
    pay(customer, monobank, second["invoices"][0]["id"])

    def assign(order):
        return operator.post(
            f"/api/operator/orders/{order['id']}/allocate",
            json={"server_id": server.id},
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(assign, [first, second]))
    assert sorted(result.status_code for result in results) == [201, 409]
    assert db.scalar(select(func.count()).select_from(Rental)) == 1
    assert len(operator.get("/api/operator/queue").json()) == 1


def test_payment_key_is_bound_to_one_invoice(clients, active_rental):
    customer = clients["customer"]
    invoice_id = customer.post(
        f"/api/rentals/{active_rental['id']}/renewal-invoice"
    ).json()["id"]
    response = customer.post(
        f"/api/invoices/{invoice_id}/payments",
        json={"idempotency_key": "initial-payment-key"},
    )
    assert response.status_code == 409

import os

import pytest
from alembic import command
from alembic.config import Config
from dotenv import load_dotenv
from fastapi.testclient import TestClient
from sqlalchemy import make_url, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import Base, get_engine
from app.main import app
from app.models import Plan, Server, User
from app.security import encrypt_password, password_hasher

PASSWORD = "Test-password-2026!"


@pytest.fixture(scope="session", autouse=True)
def test_database():
    load_dotenv()
    original_url = os.environ["DATABASE_URL"]
    url = make_url(
        os.environ.get(
            "TEST_DATABASE_URL",
            make_url(original_url)
            .set(database="vpsrent_test")
            .render_as_string(hide_password=False),
        )
    )
    if not url.database.endswith("_test"):
        raise RuntimeError("Tests require a database name ending in _test")
    if url == make_url(original_url):
        raise RuntimeError("Tests must not use the application database")
    os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)
    get_settings.cache_clear()
    get_engine.cache_clear()
    engine = get_engine()
    command.upgrade(Config("alembic.ini"), "head")
    yield engine
    engine.dispose()
    get_engine.cache_clear()
    get_settings.cache_clear()
    os.environ["DATABASE_URL"] = original_url


@pytest.fixture(autouse=True)
def clean_database(test_database):
    tables = ", ".join(f'"{name}"' for name in Base.metadata.tables)
    with test_database.begin() as connection:
        connection.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture
def db(test_database):
    with Session(test_database, expire_on_commit=False) as session:
        yield session


@pytest.fixture
def accounts(db):
    users = {}
    for role in ("customer", "operator", "support", "manager"):
        user = User(
            email=f"{role}@example.com",
            role=role,
            password_hash=password_hasher.hash(PASSWORD),
        )
        db.add(user)
        users[role] = user
    db.commit()
    return users


@pytest.fixture
def clients(accounts):
    result = {}
    for role in accounts:
        client = TestClient(app)
        response = client.post(
            "/api/auth/login",
            json={
                "email": f"{role}@example.com",
                "password": PASSWORD,
            },
        )
        assert response.status_code == 200, response.text
        client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        result[role] = client
    yield result
    for client in result.values():
        client.close()


@pytest.fixture
def inventory(db):
    plan = Plan(
        name="Starter",
        description="Small sites and bots",
        cpu=1,
        ram_gb=2,
        disk_gb=25,
        monthly_cents=169,
        annual_cents=1725,
    )
    server = Server(
        name="VPS-001",
        address="192.0.2.1",
        cpu=1,
        ram_gb=2,
        disk_gb=25,
        ssh_user="ubuntu",
        password_ciphertext=encrypt_password(PASSWORD),
    )
    db.add_all([plan, server])
    db.commit()
    return plan, server


@pytest.fixture
def paid_order(clients, inventory):
    plan, server = inventory
    customer = clients["customer"]
    response = customer.post(
        "/api/orders",
        json={
            "plan_id": plan.id,
            "term": "monthly",
        },
    )
    assert response.status_code == 201, response.text
    order = response.json()
    response = customer.post(
        f"/api/invoices/{order['invoices'][0]['id']}/test-payment",
        json={
            "outcome": "succeeded",
            "idempotency_key": "initial-payment-key",
        },
    )
    assert response.status_code == 200, response.text
    return order, server


@pytest.fixture
def active_rental(clients, paid_order):
    order, server = paid_order
    response = clients["operator"].post(
        f"/api/operator/orders/{order['id']}/allocate",
        json={"server_id": server.id},
    )
    assert response.status_code == 201, response.text
    return response.json()

from contextlib import contextmanager

from sqlalchemy import event

from app.models import Server
from app.security import encrypt_password
from tests.conftest import PASSWORD


@contextmanager
def count_queries(engine):
    statements = []

    def remember(conn, cursor, statement, *args):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", remember)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", remember)


def open_tickets(customer, count, start=0):
    return [
        customer.post(
            "/api/tickets",
            json={"subject": f"Question {start + index}", "body": "Hello"},
        ).json()["id"]
        for index in range(count)
    ]


def walk(client, path):
    """Every item of a paged list, following its cursors."""
    items, cursor = [], None
    while True:
        query = f"&cursor={cursor}" if cursor else ""
        page = client.get(f"{path}{query}").json()
        items += page["items"]
        cursor = page["next_cursor"]
        if not cursor:
            return items


def test_ticket_pages_follow_the_cursor(clients):
    customer, support = clients["customer"], clients["support"]
    ids = open_tickets(customer, 5)
    first = support.get("/api/tickets?limit=2").json()
    assert [item["id"] for item in first["items"]] == ids[::-1][:2]
    assert first["next_cursor"]
    # A reply moves the oldest ticket to the top; pages stay consistent.
    support.post(f"/api/tickets/{ids[0]}/messages", json={"body": "Hi"})
    listed = walk(support, "/api/tickets?limit=2")
    assert [item["id"] for item in listed] == [ids[0], *ids[:0:-1]]
    newest = listed[0]
    assert newest["last_message"] == {"author": "support", "body": "Hi"}
    assert newest["awaiting_support"] is False
    assert "messages" not in newest
    assert support.get("/api/tickets?cursor=broken").status_code == 422


def test_waiting_tickets_and_counts(clients):
    customer, support = clients["customer"], clients["support"]
    ids = open_tickets(customer, 3)
    support.post(f"/api/tickets/{ids[1]}/messages", json={"body": "On it"})
    support.post(f"/api/tickets/{ids[2]}/status", json={"status": "closed"})
    awaiting = support.get("/api/tickets?status=awaiting").json()["items"]
    assert [item["id"] for item in awaiting] == [ids[0]]
    assert support.get("/api/counts").json()["tickets"] == {
        "all": 3,
        "awaiting": 1,
        "open": 1,
        "in_progress": 1,
        "closed": 1,
    }
    own = customer.get("/api/tickets").json()["items"]
    assert {item["id"] for item in own} == set(ids)
    assert customer.get("/api/counts").json() == {}


def test_history_filters_run_on_the_server(clients):
    customer, support = clients["customer"], clients["support"]
    ids = open_tickets(customer, 2)
    support.post(f"/api/tickets/{ids[0]}/status", json={"status": "closed"})
    closed = support.get("/api/activity?filter=ticket_status:closed").json()
    assert [item["entity_id"] for item in closed["items"]] == [ids[0]]
    opened = walk(support, "/api/activity?filter=ticket_created&limit=1")
    assert [item["entity_id"] for item in opened] == ids[::-1]
    assert support.get("/api/activity?filter=order").status_code == 422
    operator = clients["operator"]
    assert operator.get("/api/activity?filter=ticket").status_code == 422


def test_list_queries_do_not_grow_with_rows(
    clients, test_database, active_rental, db
):
    customer, support = clients["customer"], clients["support"]
    operator = clients["operator"]

    def queries(client, path):
        with count_queries(test_database) as statements:
            assert client.get(path).status_code == 200
        return len(statements)

    open_tickets(customer, 2)
    tickets_small = queries(support, "/api/tickets")
    pool_small = queries(operator, "/api/operator/servers")
    history_small = queries(support, "/api/activity")

    open_tickets(customer, 6, start=2)
    db.add_all(
        Server(
            name=f"VPS-1{index:02d}",
            address=f"192.0.2.{100 + index}",
            cpu=1,
            ram_gb=2,
            disk_gb=25,
            ssh_user="ubuntu",
            password_ciphertext=encrypt_password(PASSWORD),
        )
        for index in range(6)
    )
    db.commit()
    assert queries(support, "/api/tickets") == tickets_small
    assert queries(operator, "/api/operator/servers") == pool_small
    assert queries(support, "/api/activity") == history_small

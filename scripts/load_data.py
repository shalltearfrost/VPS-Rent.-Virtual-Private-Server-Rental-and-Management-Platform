"""Generate several hundred thousand rows for load testing, and remove them.

    .venv/Scripts/python.exe scripts/load_data.py seed            # ~480k rows
    .venv/Scripts/python.exe scripts/load_data.py seed --scale 0.2
    .venv/Scripts/python.exe scripts/load_data.py status
    .venv/Scripts/python.exe scripts/load_data.py purge

Every generated row is reachable from a marker, so `purge` deletes exactly
what `seed` created and nothing else:
  - users       email  <role>-<n>@<tag>.load.invalid  (cannot sign in)
  - servers     name   load-<tag>-<n>, address in 198.18.0.0/15 (RFC 2544)
  - plan        name   load-<tag>, disabled, so customers never see it
  - orders, invoices, rentals, operations, tickets, messages and activity
    all belong to those users or servers.
Several data sets can coexist with different --tag values. Each command runs
in one transaction: a failure leaves the database unchanged.
"""

import argparse
import os
import re
import secrets
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from alembic.config import Config  # noqa: E402
from alembic.script import ScriptDirectory  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import Connection, make_url  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.security import encrypt_password, password_hasher  # noqa: E402

BENCHMARK_NET = "198.18.0.0/15"
# Row counts at --scale 1; totals about 480k rows.
BASE = {
    "customers": 2000,
    "staff": 5,  # operators and support agents each
    "servers": 3000,
    "orders": 20000,
    "operations": 20000,
    "tickets": 50000,
    "activity": 200000,
}
# Order layout by position g (1-based) at scale 1, scaled with the rest:
# active rentals, then expiring ones that need operator action, then ended
# rentals, then the allocation queue, then unpaid orders.
LAYOUT = {
    "active": 2300,
    "suspension_pending": 100,
    "suspended": 100,
    "ended": 10000,
    "queue": 500,
}
TABLES = (
    "users",
    "servers",
    "plans",
    "orders",
    "invoices",
    "rentals",
    "operation_requests",
    "tickets",
    "ticket_messages",
    "activity",
)


def markers(tag: str) -> dict:
    return {
        "email": f"%@{tag}.load.invalid",
        "server": f"load-{tag}-%",
        "plan": f"load-{tag}",
    }


def connect(database: str | None):
    url = make_url(get_settings().database_url)
    if database:
        url = url.set(database=database)
    return create_engine(url), url


def require_head(conn: Connection) -> None:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    head = ScriptDirectory.from_config(config).get_current_head()
    current = conn.scalar(text("SELECT version_num FROM alembic_version"))
    if current != head:
        raise SystemExit(
            f"Database schema is at {current}, expected {head}. "
            "Run: .venv/Scripts/python.exe -m alembic upgrade head"
        )


def marked_ids(conn: Connection, tag: str) -> None:
    """Temporary id tables of everything that belongs to the tag."""
    mark = markers(tag)
    for table in ("users", "orders", "rentals", "tickets", "servers"):
        conn.execute(text(f"DROP TABLE IF EXISTS load_{table}"))
    statements = [
        "CREATE TEMP TABLE load_users ON COMMIT DROP AS "
        "SELECT id FROM users WHERE email LIKE :email",
        "CREATE TEMP TABLE load_orders ON COMMIT DROP AS "
        "SELECT id FROM orders WHERE customer_id IN "
        "(SELECT id FROM load_users)",
        "CREATE TEMP TABLE load_rentals ON COMMIT DROP AS "
        "SELECT id FROM rentals WHERE order_id IN "
        "(SELECT id FROM load_orders)",
        "CREATE TEMP TABLE load_tickets ON COMMIT DROP AS "
        "SELECT id FROM tickets WHERE customer_id IN "
        "(SELECT id FROM load_users)",
        "CREATE TEMP TABLE load_servers ON COMMIT DROP AS "
        "SELECT id FROM servers WHERE name LIKE :server",
    ]
    for statement in statements:
        conn.execute(text(statement), mark)
    for table in ("load_users", "load_orders", "load_rentals", "load_tickets"):
        conn.execute(text(f"CREATE UNIQUE INDEX ON {table} (id)"))
        conn.execute(text(f"ANALYZE {table}"))


def counts(conn: Connection, tag: str) -> dict:
    marked_ids(conn, tag)
    queries = {
        "users": "SELECT count(*) FROM load_users",
        "servers": "SELECT count(*) FROM load_servers",
        "plans": "SELECT count(*) FROM plans WHERE name = :plan",
        "orders": "SELECT count(*) FROM load_orders",
        "invoices": "SELECT count(*) FROM invoices "
        "WHERE order_id IN (SELECT id FROM load_orders)",
        "rentals": "SELECT count(*) FROM load_rentals",
        "operation_requests": "SELECT count(*) FROM operation_requests "
        "WHERE rental_id IN (SELECT id FROM load_rentals)",
        "tickets": "SELECT count(*) FROM load_tickets",
        "ticket_messages": "SELECT count(*) FROM ticket_messages "
        "WHERE ticket_id IN (SELECT id FROM load_tickets)",
        "activity": "SELECT count(*) FROM activity "
        "WHERE actor_id IN (SELECT id FROM load_users)",
    }
    mark = markers(tag)
    return {
        name: conn.scalar(text(sql), mark) for name, sql in queries.items()
    }


def step(conn: Connection, label: str, sql: str, **params) -> None:
    started = time.perf_counter()
    rows = conn.execute(text(sql), params).rowcount
    took = time.perf_counter() - started
    print(f"  {label:<22} {rows:>9,} rows  {took:6.1f} s")


def seed(conn: Connection, tag: str, scale: float) -> None:
    size = {key: max(1, round(value * scale)) for key, value in BASE.items()}
    size["staff"] = BASE["staff"]
    layout = {
        key: max(1, round(value * scale)) for key, value in LAYOUT.items()
    }
    # Positions where each order group ends (cumulative).
    edge, total = {}, 0
    for key, value in layout.items():
        total += value
        edge[key] = total
    if total > size["orders"]:
        raise SystemExit("Scale too small for the order layout")
    held = edge["suspended"]
    if held > size["servers"]:
        raise SystemExit("More held rentals than servers")
    mark = markers(tag)
    leftovers = conn.scalar(
        text(
            "SELECT (SELECT count(*) FROM users WHERE email LIKE :email) "
            "+ (SELECT count(*) FROM servers WHERE name LIKE :server) "
            "+ (SELECT count(*) FROM plans WHERE name = :plan)"
        ),
        mark,
    )
    if leftovers:
        raise SystemExit(f"Tag '{tag}' already has data; purge it first")

    hidden = password_hasher.hash(secrets.token_urlsafe(32))
    print(f"Seeding tag '{tag}' at scale {scale}:")
    step(
        conn,
        "users",
        """
        INSERT INTO users (email, password_hash, role)
        SELECT r.role || '-' || g || '@' || :tag || '.load.invalid',
               :hash, r.role
        FROM (VALUES ('customer', :customers), ('operator', :staff),
                     ('support', :staff)) AS r(role, n),
             generate_series(1, r.n) AS g
        """,
        tag=tag,
        hash=hidden,
        customers=size["customers"],
        staff=size["staff"],
    )
    ids = {
        role: conn.scalars(
            text(
                "SELECT id FROM users WHERE email LIKE :email "
                "AND role = :role ORDER BY id"
            ),
            {"email": mark["email"], "role": role},
        ).all()
        for role in ("customer", "operator", "support")
    }
    conn.execute(
        text(
            "INSERT INTO plans (name, description, cpu, ram_gb, disk_gb, "
            "monthly_cents, annual_cents, enabled) VALUES (:plan, "
            "'Load-test data', 2, 4, 40, 900, 9000, false)"
        ),
        mark,
    )
    plan = conn.scalar(text("SELECT id FROM plans WHERE name = :plan"), mark)

    # Next free addresses in the benchmark range, so tags never collide.
    start = conn.scalar(
        text(
            "SELECT coalesce(max(address - inet '198.18.0.0'), 0) "
            "FROM servers WHERE address << CAST(:net AS inet)"
        ),
        {"net": BENCHMARK_NET},
    )
    if start + size["servers"] >= 2**17:
        raise SystemExit("The benchmark address range is full")
    step(
        conn,
        "servers",
        """
        INSERT INTO servers (name, address, cpu, ram_gb, disk_gb, ssh_user,
                             password_ciphertext, state)
        SELECT 'load-' || :tag || '-' || g, inet '198.18.0.0' + (:start + g),
               2, 4, 40, 'ubuntu', :secret,
               CASE WHEN g <= :pending THEN 'assigned'
                    WHEN g <= :held THEN 'suspended'
                    ELSE 'available' END
        FROM generate_series(1, :n) AS g
        """,
        tag=tag,
        start=start,
        secret=encrypt_password(secrets.token_urlsafe(24)),
        pending=edge["suspension_pending"],
        held=held,
        n=size["servers"],
    )
    servers = conn.scalars(
        text(
            "SELECT id FROM servers WHERE name LIKE :server "
            "ORDER BY substring(name from '[0-9]+$')::int"
        ),
        mark,
    ).all()

    step(
        conn,
        "orders",
        """
        INSERT INTO orders (customer_id, plan_id, plan_name, cpu, ram_gb,
                            disk_gb, price_cents, renewal_cents, term, status,
                            created_at)
        SELECT (:customers)[1 + g % cardinality(:customers)], :plan,
               'load-' || :tag, 2, 4, 40, 900, 900,
               CASE WHEN g % 5 = 0 THEN 'annual' ELSE 'monthly' END,
               CASE WHEN g <= :active THEN 'active'
                    WHEN g <= :ended THEN 'expired'
                    WHEN g <= :queue THEN 'awaiting_allocation'
                    ELSE 'awaiting_payment' END,
               now() - (:n - g) * interval '25 minutes'
        FROM generate_series(1, :n) AS g
        """,
        customers=ids["customer"],
        plan=plan,
        tag=tag,
        active=edge["active"],
        ended=edge["ended"],
        queue=edge["queue"],
        n=size["orders"],
    )
    numbered = """
        WITH o AS (
            SELECT id, customer_id, created_at,
                   row_number() OVER (ORDER BY id) AS g
            FROM orders WHERE plan_id = :plan
        )
    """
    step(
        conn,
        "invoices",
        numbered
        + """
        INSERT INTO invoices (order_id, kind, amount_cents, currency, status,
                              paid_at, created_at)
        SELECT id, 'initial', 900, 'EUR',
               CASE WHEN g <= :queue THEN 'paid' ELSE 'unpaid' END,
               CASE WHEN g <= :queue
                    THEN created_at + interval '5 minutes' END,
               created_at
        FROM o
        """,
        plan=plan,
        queue=edge["queue"],
    )
    step(
        conn,
        "rentals",
        numbered
        + """
        INSERT INTO rentals (order_id, server_id, started_at, expires_at,
                             status, power)
        SELECT id,
               CASE WHEN g <= :held THEN (:servers)[g]
                    ELSE (:servers)[1 + g % cardinality(:servers)] END,
               CASE WHEN g <= :active THEN now() - interval '10 days'
                    ELSE created_at END,
               CASE WHEN g <= :active THEN now() + interval '20 days'
                    ELSE created_at + interval '30 days' END,
               CASE WHEN g <= :active THEN 'active'
                    WHEN g <= :pending THEN 'suspension_pending'
                    WHEN g <= :held THEN 'suspended'
                    ELSE 'ended' END,
               CASE WHEN g <= :active AND g % 4 <> 0 THEN 'running'
                    ELSE 'stopped' END
        FROM o WHERE g <= :ended
        """,
        plan=plan,
        servers=servers,
        active=edge["active"],
        pending=edge["suspension_pending"],
        held=held,
        ended=edge["ended"],
    )
    rentals = """
        WITH r AS (
            SELECT r.id, o.customer_id, row_number() OVER (ORDER BY o.id) AS g
            FROM rentals r JOIN orders o ON o.id = r.order_id
            WHERE o.plan_id = :plan
        )
    """
    pending = min(edge["active"], max(1, size["operations"] // 60))
    step(
        conn,
        "operation_requests",
        rentals
        + """
        INSERT INTO operation_requests (rental_id, requested_by, kind, status,
                                        result, resolved_by, resolved_at,
                                        created_at)
        SELECT r.id, r.customer_id,
               (ARRAY['start', 'stop', 'restart'])[1 + k % 3],
               CASE WHEN k <= :pending THEN 'pending'
                    WHEN k % 9 = 0 THEN 'rejected' ELSE 'completed' END,
               CASE WHEN k <= :pending THEN NULL
                    WHEN k % 9 = 0 THEN 'Rejected during maintenance'
                    ELSE 'Done at the provider' END,
               CASE WHEN k > :pending
                    THEN (:operators)[1 + k % cardinality(:operators)] END,
               CASE WHEN k > :pending
                    THEN now() - k * interval '25 minutes'
                         + interval '20 minutes' END,
               now() - k * interval '25 minutes'
        FROM generate_series(1, :n) AS k
        JOIN r ON r.g = CASE WHEN k <= :pending THEN k
                             ELSE 1 + k % :rentals END
        """,
        plan=plan,
        pending=pending,
        rentals=edge["ended"],
        operators=ids["operator"],
        n=size["operations"],
    )
    with_server = size["tickets"] * 3 // 10
    step(
        conn,
        "tickets",
        rentals
        + """
        INSERT INTO tickets (customer_id, rental_id, subject, status,
                             last_message_at, awaiting_support, created_at)
        SELECT coalesce(r.customer_id,
                        (:customers)[1 + i % cardinality(:customers)]),
               r.id, 'Load ticket ' || i,
               (ARRAY['closed', 'closed', 'closed', 'closed', 'in_progress',
                      'in_progress', 'in_progress', 'open', 'open',
                      'open'])[1 + i % 10],
               now() - i * interval '10 minutes',
               i % 10 >= 7 OR (i % 10 BETWEEN 4 AND 6 AND i % 2 = 0),
               now() - i * interval '10 minutes' - interval '2 days'
        FROM generate_series(1, :n) AS i
        LEFT JOIN r ON i <= :with_server AND r.g = 1 + i % :rentals
        """,
        plan=plan,
        rentals=edge["ended"],
        customers=ids["customer"],
        with_server=with_server,
        n=size["tickets"],
    )
    tickets = "SELECT id FROM tickets WHERE customer_id = ANY(:customers)"
    step(
        conn,
        "ticket_messages",
        f"""
        INSERT INTO ticket_messages (ticket_id, author_id, body, created_at)
        SELECT t.id,
               CASE WHEN n = 1 OR (n = 3 AND t.awaiting_support)
                    THEN t.customer_id
                    ELSE (:support)[1 + t.id % cardinality(:support)] END,
               'Load message ' || n || ' about ' || t.subject || '. '
                   || repeat('Details of the problem. ', 6),
               t.last_message_at - (3 - n) * interval '1 hour'
        FROM tickets t, generate_series(1, 3) AS n
        WHERE t.id IN ({tickets})
        """,
        customers=ids["customer"],
        support=ids["support"],
    )

    def entity_ids(sql: str) -> list[int]:
        return conn.scalars(
            text(sql), {"plan": plan, "email": mark["email"]}
        ).all()

    orders = "SELECT id FROM orders WHERE plan_id = :plan"
    rentals_of_plan = f"SELECT id FROM rentals WHERE order_id IN ({orders})"
    entities = {
        "tickets": entity_ids(
            "SELECT t.id FROM tickets t JOIN users u ON u.id = t.customer_id "
            "WHERE u.email LIKE :email"
        ),
        "orders": entity_ids(orders),
        "invoices": entity_ids(
            f"SELECT id FROM invoices WHERE order_id IN ({orders})"
        ),
        "rentals": entity_ids(rentals_of_plan),
        "operations": entity_ids(
            "SELECT id FROM operation_requests "
            f"WHERE rental_id IN ({rentals_of_plan})"
        ),
    }
    step(
        conn,
        "activity",
        """
        WITH kinds(k, action, entity_type, result) AS (VALUES
            (0, 'ticket_created', 'ticket', 'open'),
            (1, 'ticket_reply', 'ticket', 'Support replied'),
            (2, 'ticket_status', 'ticket', 'closed'),
            (3, 'ticket_reply', 'ticket', 'Customer replied'),
            (4, 'order_created', 'order', 'Invoice created'),
            (5, 'order_created', 'order', 'Invoice created'),
            (6, 'payment_succeeded', 'invoice', 'Paid'),
            (7, 'allocated', 'rental', 'load server'),
            (8, 'operation_requested', 'operation', 'restart'),
            (9, 'operation_resolved', 'operation', 'completed'))
        INSERT INTO activity (actor_id, action, entity_type, entity_id, result,
                              created_at)
        SELECT CASE WHEN kinds.entity_type = 'ticket' AND g % 2 = 0
                         OR kinds.action = 'ticket_status'
                    THEN (:support)[1 + g % cardinality(:support)]
                    WHEN kinds.action IN ('allocated', 'operation_resolved')
                    THEN (:operators)[1 + g % cardinality(:operators)]
                    ELSE (:customers)[1 + g % cardinality(:customers)] END,
               kinds.action, kinds.entity_type,
               CASE kinds.entity_type
                    WHEN 'ticket'
                    THEN (:tickets)[1 + g % cardinality(:tickets)]
                    WHEN 'order' THEN (:orders)[1 + g % cardinality(:orders)]
                    WHEN 'invoice'
                    THEN (:invoices)[1 + g % cardinality(:invoices)]
                    WHEN 'rental'
                    THEN (:rentals)[1 + g % cardinality(:rentals)]
                    ELSE (:operations)[1 + g % cardinality(:operations)] END,
               kinds.result,
               now() - g * interval '150 seconds'
        FROM generate_series(1, :n) AS g
        JOIN kinds ON kinds.k = g % 10
        """,
        customers=ids["customer"],
        support=ids["support"],
        operators=ids["operator"],
        n=size["activity"],
        **entities,
    )
    for table in TABLES:
        conn.execute(text(f"ANALYZE {table}"))


def purge(conn: Connection, tag: str) -> None:
    marked_ids(conn, tag)
    mark = markers(tag)
    # A real order may have been allocated to a load server in the UI; keep
    # such servers instead of failing on the foreign key.
    kept = conn.scalar(
        text(
            "SELECT count(DISTINCT server_id) FROM rentals "
            "WHERE server_id IN (SELECT id FROM load_servers) "
            "AND order_id NOT IN (SELECT id FROM load_orders)"
        )
    )
    print(f"Purging tag '{tag}':")
    steps = [
        (
            "activity",
            "DELETE FROM activity "
            "WHERE actor_id IN (SELECT id FROM load_users)",
        ),
        (
            "ticket_messages",
            "DELETE FROM ticket_messages "
            "WHERE ticket_id IN (SELECT id FROM load_tickets)",
        ),
        (
            "tickets",
            "DELETE FROM tickets WHERE id IN (SELECT id FROM load_tickets)",
        ),
        (
            "operation_requests",
            "DELETE FROM operation_requests "
            "WHERE rental_id IN (SELECT id FROM load_rentals)",
        ),
        (
            "payments",
            "DELETE FROM payments WHERE invoice_id IN "
            "(SELECT id FROM invoices WHERE order_id IN "
            "(SELECT id FROM load_orders))",
        ),
        (
            "invoices",
            "DELETE FROM invoices "
            "WHERE order_id IN (SELECT id FROM load_orders)",
        ),
        (
            "rentals",
            "DELETE FROM rentals WHERE id IN (SELECT id FROM load_rentals)",
        ),
        (
            "orders",
            "DELETE FROM orders WHERE id IN (SELECT id FROM load_orders)",
        ),
        (
            "payment_cards",
            "DELETE FROM payment_cards "
            "WHERE customer_id IN (SELECT id FROM load_users)",
        ),
        (
            "servers",
            "DELETE FROM servers WHERE id IN "
            "(SELECT id FROM load_servers) AND NOT EXISTS "
            "(SELECT 1 FROM rentals WHERE rentals.server_id = servers.id)",
        ),
        (
            "plans",
            "DELETE FROM plans WHERE name = :plan AND NOT EXISTS "
            "(SELECT 1 FROM orders WHERE orders.plan_id = plans.id)",
        ),
        ("users", "DELETE FROM users WHERE id IN (SELECT id FROM load_users)"),
    ]
    for label, sql in steps:
        step(conn, label, sql, **mark)
    if kept:
        print(
            f"  kept {kept} load server(s) that real rentals use; "
            "purge again after those rentals end"
        )
    for table in TABLES:
        conn.execute(text(f"ANALYZE {table}"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("command", choices=("seed", "purge", "status"))
    parser.add_argument(
        "--tag",
        default="load",
        help="name of the data set (lowercase letters and digits)",
    )
    parser.add_argument(
        "--scale", type=float, default=1.0, help="row count multiplier"
    )
    parser.add_argument(
        "--database",
        help="database name on the same server (default: from .env)",
    )
    args = parser.parse_args()
    # .env and the settings it feeds are read from the project root.
    os.chdir(ROOT)
    if not re.fullmatch(r"[a-z0-9]{1,16}", args.tag):
        parser.error("--tag must be 1-16 lowercase letters or digits")
    if not 0.01 <= args.scale <= 10:
        parser.error("--scale must be between 0.01 and 10")

    engine, url = connect(args.database)
    print(f"Database: {url.render_as_string(hide_password=True)}")
    started = time.perf_counter()
    with engine.begin() as conn:
        require_head(conn)
        if args.command == "seed":
            seed(conn, args.tag, args.scale)
        elif args.command == "purge":
            purge(conn, args.tag)
        found = counts(conn, args.tag)
    for table, count in found.items():
        print(f"  {table:<22} {count:>9,} rows tagged '{args.tag}'")
    took = time.perf_counter() - started
    print(f"Total {sum(found.values()):,} rows, {took:.1f} s")


if __name__ == "__main__":
    main()

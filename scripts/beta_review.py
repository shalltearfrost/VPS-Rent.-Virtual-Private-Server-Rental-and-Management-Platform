"""Run a repeatable local review without changing the application database."""

import argparse
import os
from datetime import timedelta
from pathlib import Path

from alembic import command
from alembic.config import Config
from dotenv import load_dotenv
from sqlalchemy import create_engine, make_url, select, text
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
REVIEW_DATABASE = "vpsrent_beta_review_test"
REVIEW_PASSWORD = "Review-password-2026!"


def configure(sandbox=False, port=8001):
    load_dotenv(ROOT / ".env")
    original = make_url(os.environ["DATABASE_URL"])
    if original.drivername != "postgresql+psycopg":
        raise SystemExit("The review requires PostgreSQL with psycopg.")
    database = "vpsrent_monobank_sandbox_test" if sandbox else REVIEW_DATABASE
    target = original.set(database=database)
    if original == target:
        raise SystemExit("Keep DATABASE_URL pointed at the application DB.")
    os.environ["DATABASE_URL"] = target.render_as_string(hide_password=False)
    os.environ["DEMO_PASSWORD"] = REVIEW_PASSWORD
    os.environ["COOKIE_SECURE"] = "false"
    if not sandbox:
        os.environ["MONOBANK_TOKEN"] = ""
        os.environ["MONOBANK_TEST_TOKEN"] = ""
    os.environ["PUBLIC_URL"] = f"http://127.0.0.1:{port}"
    if sandbox:
        from app.billing.monobank import configured_gateway

        gateway = configured_gateway()
        if gateway is None:
            raise SystemExit("Set MONOBANK_TEST_TOKEN before sandbox review.")
        gateway.ensure_sandbox()
    os.chdir(ROOT)
    return original, target


def prepare(original, target) -> None:
    admin = create_engine(
        original.set(database="postgres"),
        isolation_level="AUTOCOMMIT",
        connect_args={"connect_timeout": 5},
    )
    try:
        with admin.connect() as connection:
            exists = connection.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": target.database},
            )
            if not exists:
                connection.execute(
                    text(f'CREATE DATABASE "{target.database}"')
                )
    finally:
        admin.dispose()
    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
    from app.seed import main as seed

    seed()
    print(f"Review database ready: {target.database}")
    print("Use the review accounts documented in docs/beta-review.md.")


def expire_rental(rental_id: int) -> None:
    from app.database import get_engine
    from app.models import Rental
    from app.security import now
    from app.services import flag_expired, record

    with Session(get_engine()) as db, db.begin():
        rental = db.scalar(
            select(Rental).where(Rental.id == rental_id).with_for_update()
        )
        if not rental or rental.status != "active":
            raise SystemExit("Choose an active review rental.")
        rental.started_at = min(rental.started_at, now() - timedelta(days=31))
        rental.expires_at = now() - timedelta(seconds=1)
        record(
            db,
            None,
            "review_expiry_fixture",
            "rental",
            rental.id,
            "Review-only clock adjustment",
        )
        db.flush()
        flag_expired(db)
    print(f"Review rental {rental_id} is awaiting suspension.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--sandbox", action="store_true")
    prepare_parser.add_argument("--port", type=int, default=8001)
    serve = subparsers.add_parser("serve")
    serve.add_argument("--port", type=int, default=8001)
    serve.add_argument("--sandbox", action="store_true")
    expire = subparsers.add_parser("expire-rental")
    expire.add_argument("--id", type=int, required=True)
    expire.add_argument("--sandbox", action="store_true")
    args = parser.parse_args()
    original, target = configure(args.sandbox, getattr(args, "port", 8001))
    if args.action == "prepare":
        prepare(original, target)
    elif args.action == "expire-rental":
        if args.id <= 0:
            parser.error("The rental ID must be positive.")
        expire_rental(args.id)
    else:
        import uvicorn

        uvicorn.run("app.main:app", host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()

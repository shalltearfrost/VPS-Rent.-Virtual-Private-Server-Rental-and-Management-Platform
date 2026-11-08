import os
import secrets

from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_engine
from app.models import Plan, Server, User
from app.security import encrypt_password, password_hasher


def main() -> None:
    load_dotenv()
    password = os.environ.get("DEMO_PASSWORD")
    if not password or len(password) < 12:
        raise SystemExit("Set DEMO_PASSWORD to at least 12 characters")
    with Session(get_engine()) as db, db.begin():
        for role in ("customer", "operator", "support", "manager"):
            email = f"{role}@example.com"
            if not db.scalar(select(User.id).where(User.email == email)):
                db.add(
                    User(
                        email=email,
                        role=role,
                        password_hash=password_hasher.hash(password),
                    )
                )
        plans = [
            ("Starter", "Small sites and bots", 1, 2, 25, 169, 1725),
            ("Standard", "APIs and team projects", 2, 4, 50, 282, 2875),
            ("Pro", "Larger Linux workloads", 4, 8, 100, 670, 6832),
        ]
        for index, values in enumerate(plans, start=1):
            name, description, cpu, ram, disk, monthly, annual = values
            if not db.scalar(select(Plan.id).where(Plan.name == name)):
                db.add(
                    Plan(
                        name=name,
                        description=description,
                        cpu=cpu,
                        ram_gb=ram,
                        disk_gb=disk,
                        monthly_cents=monthly,
                        annual_cents=annual,
                    )
                )
            server_name = f"VPS-{index:03d}"
            if not db.scalar(
                select(Server.id).where(Server.name == server_name)
            ):
                db.add(
                    Server(
                        name=server_name,
                        address=f"192.0.2.{index}",
                        cpu=cpu,
                        ram_gb=ram,
                        disk_gb=disk,
                        ssh_user="ubuntu",
                        password_ciphertext=encrypt_password(
                            secrets.token_urlsafe(24)
                        ),
                    )
                )
    print("Demo accounts, plans and documentation-address servers are ready.")


if __name__ == "__main__":
    main()

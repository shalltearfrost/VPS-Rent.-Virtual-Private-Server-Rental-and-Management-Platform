import secrets
from pathlib import Path

from cryptography.fernet import Fernet


def main() -> None:
    target = Path(".env")
    if target.exists():
        print("Existing .env preserved.")
        return
    password = secrets.token_urlsafe(24)
    key = Fernet.generate_key().decode()
    target.write_text(
        "DATABASE_URL=postgresql+psycopg://"
        f"vpsrent:{password}@127.0.0.1:55432/vpsrent\n"
        f"POSTGRES_PASSWORD={password}\n"
        f"CREDENTIAL_KEY={key}\n"
        f"DEMO_PASSWORD={secrets.token_urlsafe(18)}\n"
        "COOKIE_SECURE=false\n",
        encoding="utf-8",
    )
    print("Created .env with random local credentials.")


if __name__ == "__main__":
    main()

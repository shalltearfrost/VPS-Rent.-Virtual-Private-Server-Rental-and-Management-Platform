import argparse
import os
import subprocess
import urllib.request
import zipfile
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime"
BIN = RUNTIME / "postgres" / "pgsql" / "bin"
DATA = RUNTIME / "postgres-data"
URL = (
    "https://get.enterprisedb.com/postgresql/"
    "postgresql-17.11-3-windows-x64-binaries.zip"
)


def run(program: str, *arguments: str, check: bool = True):
    return subprocess.run(
        [str(BIN / f"{program}.exe"), *arguments],
        check=check,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["start", "stop", "status"])
    args = parser.parse_args()
    if os.name != "nt":
        raise SystemExit(
            "This helper supports Windows. On Linux/macOS, install "
            "PostgreSQL locally and configure DATABASE_URL in .env."
        )
    load_dotenv(ROOT / ".env")
    if args.action == "stop":
        run("pg_ctl", "-D", str(DATA), "-m", "fast", "-w", "stop")
        return
    if args.action == "status":
        run("pg_ctl", "-D", str(DATA), "status")
        return
    if not (BIN / "initdb.exe").exists():
        downloads = RUNTIME / "downloads"
        downloads.mkdir(parents=True, exist_ok=True)
        archive = downloads / "postgresql.zip"
        if not archive.exists():
            print("Downloading PostgreSQL binaries from EnterpriseDB…")
            urllib.request.urlretrieve(URL, archive)
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.infolist():
                if member.filename.startswith(
                    ("pgsql/bin/", "pgsql/lib/", "pgsql/share/")
                ):
                    bundle.extract(member, RUNTIME / "postgres")
    if not (DATA / "PG_VERSION").exists():
        password_file = RUNTIME / "init-password.txt"
        password_file.write_text(
            os.environ["POSTGRES_PASSWORD"], encoding="utf-8"
        )
        try:
            run(
                "initdb",
                "-D",
                str(DATA),
                "-U",
                "vpsrent",
                "--pwfile",
                str(password_file),
                "--auth=scram-sha-256",
                "--encoding=UTF8",
                "--locale=C",
            )
        finally:
            password_file.unlink(missing_ok=True)
    if run("pg_ctl", "-D", str(DATA), "status", check=False).returncode:
        run(
            "pg_ctl",
            "-D",
            str(DATA),
            "-l",
            str(RUNTIME / "postgresql.log"),
            "-o",
            "-p 55432 -h 127.0.0.1",
            "-w",
            "start",
        )
    with psycopg.connect(
        host="127.0.0.1",
        port=55432,
        dbname="postgres",
        user="vpsrent",
        password=os.environ["POSTGRES_PASSWORD"],
        autocommit=True,
    ) as connection:
        for name in ("vpsrent", "vpsrent_test"):
            exists = connection.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s", (name,)
            ).fetchone()
            if not exists:
                connection.execute(
                    psycopg.sql.SQL("CREATE DATABASE {}").format(
                        psycopg.sql.Identifier(name)
                    )
                )
    print("PostgreSQL is running at 127.0.0.1:55432.")


if __name__ == "__main__":
    main()

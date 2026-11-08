Andrii Moroz · Artem Ankudinov · Illia Yerokhin

# VPS Rent — Alpha

FastAPI + PostgreSQL rental platform.

## Run

Requirements: Python 3.12+ and PostgreSQL 17, or Docker Desktop for the database.
The repository's current environment uses Python 3.13 and a local PostgreSQL 17.

From the repository root, on Windows PowerShell:

```powershell
python -m venv .venv
python -m pip --python .venv install -r requirements.lock
.venv/Scripts/python.exe scripts/configure.py
```

This creates an ignored `.env` containing random database, encryption and demo
credentials. Preserve `CREDENTIAL_KEY` when restarting or moving the database:
it decrypts the stored server passwords. Never commit `.env`.

Start PostgreSQL with either option:

```powershell
docker compose up -d --wait
```

Or, on Windows without Docker, use the project-local PostgreSQL helper. It
downloads official EnterpriseDB binaries into `.runtime/`, creates its own
database cluster, and listens only on `127.0.0.1:55432`. It requires no Windows
service and does not modify an existing PostgreSQL installation:

```powershell
.venv/Scripts/python.exe scripts/windows_database.py start
```

Apply the schema, create demo accounts and start the application:

```powershell
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m app.seed
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000**. Interactive API documentation is at `/docs`;
database health is `/api/health`. On Linux/macOS, use `.venv/bin/python` for
the application commands; Docker works with the same `.env` and port.

The seed command is idempotent. Accounts:

| Account | Role |
| --- | --- |
| customer@example.com | Customer |
| operator@example.com | Hosting operator |
| support@example.com | Support agent |
| manager@example.com | Plan manager |

All seeded accounts use `DEMO_PASSWORD` from your local `.env`. Registration
always creates a customer. There is no frontend role switch or public endpoint
for changing roles. Use a separate browser profile/private window for the
operator if keeping a customer session open.

`app.seed` loads `.env` itself; no manual environment-variable export is needed.
The three seeded servers use **192.0.2.0/24 documentation addresses**. They are
database inventory for the Alpha and cannot be reached over SSH. Operators can
add real, already provisioned VPS credentials in Server pool. Start/stop/restart,
suspension and preparation are recorded manual workflows: this version does not
call a provider API or perform actual host commands. Confirm actions only after
performing them at the provider when using real infrastructure.

Stop Uvicorn with Ctrl+C. For the Windows database:

```powershell
.venv/Scripts/python.exe scripts/windows_database.py stop
```

Docker alternative: `docker compose stop`. Neither stop command deletes data.

After the initial setup, Windows can also launch the application in a hidden
background process using `./scripts/serve.ps1 -Background`. Stop that process
with `./scripts/stop.ps1`; the stop script verifies the executable and command
before stopping it. These scripts do not install dependencies or reset data.

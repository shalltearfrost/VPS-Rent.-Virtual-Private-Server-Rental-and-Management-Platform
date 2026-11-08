Andrii Moroz · Artem Ankudinov · Illia Yerokhin

# VPS Rent — Alpha

FastAPI + PostgreSQL rental platform with the approved white/black interface,
Public Sans, blue actions, green success states and red errors. The frontend is
HTML/CSS/JavaScript served by FastAPI. Data survives browser and application
restarts; the browser never stores the database or authentication token in
localStorage.

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

## Demonstrate

1. Register a customer or sign in. Choose one of the three plans and select a
   monthly or annual term. Place the order. PostgreSQL receives an immutable
   configuration/price snapshot and an unpaid invoice.
2. Expand the order row. Try **Test payment failure**: the order remains unpaid.
   Choose **Test payment success**: the invoice is paid and the order enters
   the allocation queue. My servers shows **Waiting for allocation** on the right.
3. Sign in as the operator. Allocation shows matching available servers.
   Assign one. The order and server are locked in a transaction, a rental is
   inserted and its term starts at allocation.
4. Return to the customer. My servers opens the compact control panel. The
   command is under IP address; Password/Show is under Default user. Show
   makes an authenticated request and decrypts the password for the owner only.
5. Request Stop. The panel keeps Running and disables the operation buttons
   while pending. The operator records completion or rejection in Operations.
   Completed Stop changes the customer button to Start; Restart is disabled
   while stopped. Completed Start restores Stop and Restart.
6. Under My servers → Renew rentals, create a renewal invoice. A successful
   payment adds exactly 30 days to the previous expiration; failed and repeated
   payment confirmations do not extend it again.
7. Open a support ticket and reply as the support agent. Only that customer
   and support can read the conversation. Staff status changes appear in history.

The expiry worker scans PostgreSQL every 30 seconds. Expired rentals await
suspension. The operator confirms suspension and then preparation with a new
server password. Until preparation, a server cannot be allocated again.

## Verification

Tests require a **separate database whose name ends in `_test`**. The Windows
helper creates `vpsrent_test`. With Docker, create it explicitly:

```powershell
docker compose exec db createdb -U vpsrent vpsrent_test
```

The test suite defaults to the application's connection details with database
name `vpsrent_test`; set `TEST_DATABASE_URL` to override it. It refuses the
application database, and truncates only the explicitly selected test database.

```powershell
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check app scripts tests migrations
.venv/Scripts/python.exe -m ruff format --check app scripts tests migrations
.venv/Scripts/python.exe -m alembic check
node --check app/static/app.js
```

Tests use real PostgreSQL and the real FastAPI routes. They cover the product
flow, permissions, ownership, duplicate and concurrent payments, simultaneous
allocation, renewals, expiration, preparation and support. The browser review
also completed registration, annual ordering, failed/successful payment,
operator allocation, Show/Hide, Stop and operator completion; the panel then
showed Start with Restart disabled. A 390px viewport had no horizontal overflow.

## Design and responsibilities

- [Database entities, constraints, indexes and ER diagram](docs/database.md)
- [Generated PostgreSQL DDL](docs/schema.sql)
- [Architecture and request flow](docs/architecture.md)
- [Team responsibilities, Stage 1 changes and open risks](docs/team.md)
- [Verification results](docs/verification.md)

Backend modules: `models.py` defines the schema; `security.py` handles sessions
and credentials; `services.py` contains transaction/state logic; `api.py` enforces
role permissions and maps requests; `presenters.py` selects safe response fields.
`migrations/` contains the versioned initial schema. The approved design is
implemented in `app/static/`. Fonts and their open license are stored locally.

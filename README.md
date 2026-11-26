Andrii Moroz Â· Artem Ankudinov Â· Illia Yerokhin

# VPS Rent â€” Beta

FastAPI + PostgreSQL rental platform, version 0.3.0.

The coursework product is Linux VPS rental and management. Minecraft hosting,
game-server panels, proxy hosting and supplier resale are outside its scope.

## Beta submission

- [Requirements status and Alpha issue resolutions](docs/beta.md)
- [Live review instructions for every role](docs/beta-review.md)
- [Team contributions and scope changes](docs/team.md)
- [Database design](docs/database.md), [full ER diagram](docs/database.mmd)
- [Architecture, permissions and request flow](docs/architecture.md)

The supplied Beta rubric requires a working application and real PostgreSQL;
it does not require purchasing live VPS inventory. The seed uses explicitly
documented example IPs. Infrastructure actions follow the manual operator
workflow from Stage 1. They do not execute SSH or provider commands.

## Run

Requirements: Python 3.12+ and PostgreSQL 17.
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

On Windows, start PostgreSQL with the project-local helper. It
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
database health is `/api/health`. On Linux/macOS, install PostgreSQL 17 locally,
create a database and database user, and set `DATABASE_URL` in `.env` to their
connection details using the `postgresql+psycopg://` scheme. Use
`.venv/bin/python` for the application commands.

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
database inventory for the Beta and cannot be reached over SSH. Operators can
add real, already provisioned VPS credentials in Server pool. Start/stop/restart,
suspension and preparation are recorded manual workflows: this version does not
call a provider API or perform actual host commands. Confirm actions only after
performing them at the provider when using real infrastructure.

## Google sign-in

Customers can sign in with Google next to the email/password form. The button appears when both Google OAuth credentials are configured.

1. In [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
   configure the OAuth consent screen (External; while it is in Testing, add
   your Google accounts as test users).
2. Create an **OAuth client ID** of type **Web application** and add the
   authorized redirect URI `{PUBLIC_URL}/api/auth/google/callback`, locally
   `http://127.0.0.1:8000/api/auth/google/callback`. It must match `PUBLIC_URL`
   exactly: `localhost` and `127.0.0.1` are different addresses, and open the
   app at the same address so the cookies match.
3. Put the client values in `.env` and restart the application:

   ```
   GOOGLE_CLIENT_ID=1234567890-abc.apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=...
   ```

A first Google sign-in with a new email creates a customer account. To connect
an existing account, sign in with its password and select **Link Google account**
within ten minutes. The verified Google email must match that account.

## Load-test data

`scripts/load_data.py` fills the database with about 480,000 related rows
(2,000 customers, 3,000 servers, 20,000 orders, 50,000 tickets with 150,000
messages, 200,000 history records) in roughly 15 seconds, and removes exactly
those rows again:

```powershell
.venv/Scripts/python.exe scripts/load_data.py seed     # --scale 0.2 for fewer rows
.venv/Scripts/python.exe scripts/load_data.py status
.venv/Scripts/python.exe scripts/load_data.py purge
```

Generated accounts use `@<tag>.load.invalid` emails and cannot sign in;
servers are named `load-<tag>-N` with 198.18.0.0/15 test addresses. Use
`--tag` to keep several data sets apart and `--database` to target another
database on the same server (for example `vpsrent_test`). Each command runs
in one transaction. Purge never touches real rows; if a real order was
allocated to a generated server, that server is kept and reported.

Stop Uvicorn with Ctrl+C. For the Windows database:

```powershell
.venv/Scripts/python.exe scripts/windows_database.py stop
```

Stopping the database preserves its data.

## Monobank test payments

Set `MONOBANK_TEST_TOKEN` in your ignored `.env` using a sandbox token from
[Monobank](https://api.monobank.ua/). `MONOBANK_TOKEN` is an equivalent setting;
use one name. The backend verifies a `test_` merchant and rejects live tokens.
With no token, payment creation returns HTTP 503. There is no local endpoint
that can mark a Monobank invoice paid without bank confirmation.

The catalogue and customer invoices use EUR. Before each new payment, the
backend obtains the official EUR/UAH sell rate, rounds half up to kopecks and
persists the exact UAH charge. The bank receives UAH (`ccy=980`), avoiding its
implicit conversion of foreign-currency invoices. An existing pending payment
keeps its original quote. Amount, currency, bank invoice ID and references are
checked before fulfillment. A redirect alone never pays an invoice.

Card details are entered only on Monobank's hosted page. Use synthetic test
card `4242424242424242`, future expiry and dummy CVV; the sandbox does not
transfer real money. Its fake 3-D Secure page lets you confirm or decline.
Selecting **Save card for automatic renewal** stores an encrypted test card
token and enables renewal for the assigned rental. Customers can turn renewal
off and remove saved cards. Tokens never appear in API responses or logs.

Set `PUBLIC_URL=http://127.0.0.1:8000` for the normal local app. For signed
callbacks use `PUBLIC_URL=https://your-public-host`, routed to the same app.
The legacy name `MONOBANK_PUBLIC_URL` is supported. The webhook is
`POST /api/payments/monobank/webhook`. Localhost uses authenticated bank status
checks on the return page plus background reconciliation. Public deployment
requires HTTPS and `COOKIE_SECURE=true`.

Automatic renewal reserves a durable attempt before contacting the bank.
Ambiguous charges are blocked for review, rather than retried as new charges.
Late or duplicate-invoice payments queue a refund. A processing refund stays
**Refund pending** until bank confirmation. See [payment reliability](docs/payment-reliability.md).

To run the isolated real-sandbox review:

```powershell
.venv/Scripts/python.exe -m scripts.beta_review prepare --sandbox --port 8002
.venv/Scripts/python.exe -m scripts.beta_review serve --sandbox --port 8002
```

Open http://127.0.0.1:8002 and use the four review accounts with password
`Review-password-2026!`. This helper verifies the sandbox merchant and uses
`vpsrent_monobank_sandbox_test`, separate from the application database.
Never expose these documented review credentials publicly.

After the initial setup, Windows can also launch the application in a hidden
background process using `./scripts/serve.ps1 -Background`. Stop that process
with `./scripts/stop.ps1`; the stop script verifies the executable and command
before stopping it. These scripts do not install dependencies or reset data.

## Verify

Run these commands from the repository root with PostgreSQL available:

```powershell
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check app tests scripts
.venv/Scripts/python.exe -m alembic check
.venv/Scripts/python.exe -m scripts.check_schema
```

Tests use a separate `vpsrent_test` database, or `TEST_DATABASE_URL` if supplied.
They refuse the application database and require a database name ending in
`_test`. Test tables are cleared between cases. The Windows database helper
creates the default test database alongside the application database.

For an isolated browser review, use `scripts/beta_review.py` as described in
[the review guide](docs/beta-review.md). It preserves the normal application
database and binds only to localhost. Use `--sandbox` for real test API calls;
without that flag bank payments are disabled.

The schema audit compares the model with all migrations, documented SQL, the
live database and the full ER diagram. It writes its non-sensitive report to
`outputs/beta-schema-audit.json` without changing the database.

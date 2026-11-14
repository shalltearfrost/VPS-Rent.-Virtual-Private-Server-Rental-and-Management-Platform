Andrii Moroz · Artem Ankudinov · Illia Yerokhin

# VPS Rent — Alpha

FastAPI + PostgreSQL rental platform.

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
database inventory for the Alpha and cannot be reached over SSH. Operators can
add real, already provisioned VPS credentials in Server pool. Start/stop/restart,
suspension and preparation are recorded manual workflows: this version does not
call a provider API or perform actual host commands. Confirm actions only after
performing them at the provider when using real infrastructure.

## Payments (Monobank)

Payments use the Monobank acquiring API. Invoices are in euro and Monobank
charges them in euro directly (`ccy` 978), without currency conversion.

1. Get a test token at https://api.monobank.ua/ (no real money is charged; any
   card number that passes the Luhn check works on the payment page).
2. Put it in `.env` as `MONOBANK_TOKEN=...` and restart the application.
   Without a token the rest of the app works and payment buttons return 503.
3. Set `PUBLIC_URL` to the address customers open, e.g.
   `https://vps.example.org`. Monobank returns customers there after paying.
   Only an **https** `PUBLIC_URL` enables webhooks
   (`/api/payments/monobank/webhook`, verified with Monobank's ECDSA key).
   Locally (`http://127.0.0.1:8000`) the background worker and the payment
   status page poll Monobank instead, so payments still complete.

Customers can tick "Save card for automatic renewal" when paying. The card
token is stored encrypted, and the server page lets them choose the card for
automatic renewal or remove it. Saving cards (`saveCardData`) must be enabled
for the merchant token by Monobank. Optional settings:

| Variable | Default | Meaning |
| --- | --- | --- |
| `AUTO_RENEW_DAYS_BEFORE` | 3 | Start charging this many days before expiry |
| `AUTO_RENEW_RETRY_HOURS` | 12 | Wait between failed automatic charges |
| `PAYMENT_VALIDITY_SECONDS` | 3600 | Lifetime of a Monobank payment page |
| `MONOBANK_WALLET_PREFIX` | vpsrent | Prefix for per-customer card wallets |

For deployment, also set `COOKIE_SECURE=true` and serve the app over https.
Every application process runs the expiry/billing worker; row locks with
`SKIP LOCKED` and unique indexes keep it safe with several workers.

Stop Uvicorn with Ctrl+C. For the Windows database:

```powershell
.venv/Scripts/python.exe scripts/windows_database.py stop
```

Stopping the database preserves its data.

After the initial setup, Windows can also launch the application in a hidden
background process using `./scripts/serve.ps1 -Background`. Stop that process
with `./scripts/stop.ps1`; the stop script verifies the executable and command
before stopping it. These scripts do not install dependencies or reset data.

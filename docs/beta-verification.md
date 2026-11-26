Andrii Moroz · Artem Ankudinov · Illia Yerokhin

# Beta 0.3.0 verification

Verified on 18 November 2026, Europe/Warsaw, using Windows, Python 3.13,
PostgreSQL 17.11 and Chrome. Fixes are pushed to
[PR #1](https://github.com/shalltearfrost/VPS-Rent.-Virtual-Private-Server-Rental-and-Management-Platform/pull/1),
commits `218a683` and `080cee0`. The shared workspace integrates them with the
existing Beta, preserving its role and operation concurrency regressions.

## Automated checks

| Check | Result |
| --- | --- |
| Integrated Beta `python -m pytest -q --tb=short` | 52 passed in 44.76 seconds |
| Corrected PR, isolated PostgreSQL database | 46 passed in 38.86 seconds |
| `python -m ruff check app tests scripts` | Passed |
| `node --check app/static/app.js` | Passed |
| `python -m alembic check` | No new upgrade operations |
| `python -m scripts.check_schema` | 14 tables, 127 columns, 22 foreign keys match |
| Previous Beta backup restored and upgraded | Existing records preserved |
| Review preparation repeated | Idempotent; records preserved |

PostgreSQL is real in every test. Deterministic gateway tests replace only the
HTTP transport. One non-blocking Starlette/HTTPX deprecation warning remains;
no tests fail. Coverage includes all Stage 1 requirements, role read/write
matrices, ownership, CSRF, registration escalation, order snapshots, concurrent
payments/allocation/operation resolution, exact renewals and suspension.

Payment regressions cover ambiguous charge recovery, crash safety, competing
dispatchers, processing refunds, mismatched amounts/currencies/final amounts,
stale/replayed/forged callbacks, invalid exchange rates and live-token refusal.
The schema audit compares models, migrations, documented SQL, live database
keys/checks/indexes and the full ER diagram. Alembic head is `b8109fd1b2aa`.

## PR defects and resolutions

1. A bank-accepted automatic debit followed by a timeout could be retried as a
   new charge. The worker now commits a durable reference/quote and uncertain
   marker before dispatch. Ambiguity blocks a new debit; reliable signed
   confirmation can recover the same attempt.
2. A processing refund was reported as completed. Refunds now have durable
   pending state and a stable reference, and wait for bank confirmation.
3. Status parsing discarded amount, currency and final amount. Settlement now
   validates them against the persisted charge before fulfillment.

Real testing found another issue: Monobank accepted EUR creation but reported
the attempted charge in UAH. Strict validation rejected that mismatch. New
requests freeze an explicit UAH quote from the official public EUR/UAH sell
rate, rounded half up to kopecks. Existing pending attempts retain their quote.
The first failed EUR sandbox attempt was reconciled as a test-only fixture
adjustment; no successful payment or rental was fabricated. Subsequent real
checkout, renewal, automatic debit and refund used exact saved UAH quotes.

Frontend fixes preserve Disabled plan labels, clear a submitted plan selection,
read rental data after payment reconciliation commits, hide payment retry after
expiry and allow saved-card removal after a rental ends.

## Real Monobank sandbox

The application ran at `http://127.0.0.1:8002` against the separate
`vpsrent_monobank_sandbox_test` database. Merchant details verified a sandbox
merchant before financial endpoints. Synthetic card `4242424242424242`, future
expiry and dummy CVV were entered only on the hosted test page. No real money
was transferred.

| Scenario | Observed result |
| --- | --- |
| Merchant details and signing key | Real API reachable; test merchant verified; official ECDSA key parsed. |
| Initial checkout | Frontend opened bank page; authenticated success paid invoice and queued allocation. |
| Declined/interrupted authorization | Bank failure left invoice unpaid and expiry unchanged; retry available. |
| Operator allocation | Paid Starter order assigned through the UI; customer saw stored resources, documentation IP and 30-day term. |
| Saved test card | Bank token encrypted in PostgreSQL; masked label shown in server panel. |
| Automatic renewal | Review-only expiry moved into renewal window; one real wallet charge succeeded and expiry increased exactly 30 days. Later cycles did not debit again. |
| Manual renewal | Hosted success added exactly 30 days. Refreshed frontend showed 19 January 2027 before the later expiry fixture. |
| Success replay | Repeated reads and another payment request returned original success without another charge or extension. |
| Late renewal | Review helper expired rental after checkout opened; successful payment left renewal unpaid and queued refund. |
| Refund | Real bank status reversed; application recorded refunded, one refund activity, no extension and no review flag. |
| Card removal | Sandbox-backed DELETE returned 204; no active cards or renewal consent remained. Browser confirmed removal controls disappeared. |
| Restart/persistence | FastAPI restart preserved sessions, paid invoices, renewal, refund and role screens. |

Real network/crash failures cannot all be induced on demand. Deterministic
transport fixtures cover these branches. External webhook delivery was not
exercised because localhost is not a public HTTPS origin. Local reconciliation
uses authenticated bank status; signature, replay and forgery checks are tested
separately. Deployment must configure HTTPS and verify actual callback delivery.

## Role and lifecycle checks

The running API passed a 36-request role read matrix, forbidden writes,
anonymous refusal, registration and foreign-customer 404 checks. Stop and Start
completed; Restart was rejected with a reason. Duplicate resolution was refused.
Support exchanged messages and changed statuses; closed tickets rejected replies.
Manager created, edited and disabled a plan while an existing order retained its
price. Logout invalidated each test session.

The browser separately verified all four workspaces, checkout/allocation,
manual renewal, refund, support replies/status, manager editing, backend role
refusal, suspension and ended-rental controls. Expired operations, password
reveal, renewal, auto-renew enablement and new payments returned HTTP 409.
Operator suspension was confirmed in the UI; preparation with different fixture
credentials made inventory available. Repeated preparation was refused.
The final result tab had no error-level console messages.

## Upgrade retention and reports

A previous Beta backup restored into a separate database upgraded from
`19364610a068` to the merged head. Five users, four plans, three orders, two
rentals, six payments, four servers, one session, three operations, four
invoices, one ticket, two messages and 30 activity rows retained their IDs and
existing values. Expiry and encrypted credentials stayed unchanged; old payment
outcomes became canonical statuses. Source databases were backed up before
upgrade. The historical checkout ledger is retained.

Non-sensitive reports: `outputs/beta-schema-audit.json`,
`outputs/beta-monobank-sandbox.json`, `outputs/beta-live-api-checks.json` and
`outputs/beta-upgrade-retention.json`. They contain no token or passwords.

## Browser evidence

- [Successful manual renewal](screenshots/beta-monobank-renewal.jpg)
- [Confirmed sandbox refund](screenshots/beta-monobank-refund.jpg)
- [Support conversation](screenshots/beta-payment-support.jpg)
- [Manager plan list](screenshots/beta-payment-manager.jpg)
- [Suspension before preparation](screenshots/beta-payment-suspension.jpg)
- [Backend role refusal](screenshots/beta-payment-forbidden.jpg)

All infrastructure data is a review fixture. No supplier host was operated.
The product remains Linux VPS rental with manual provider actions. Minecraft,
proxy resale, supplier purchasing and production acquiring are outside scope.
Remaining release work is deployment/HTTPS, external callback verification,
production hardening, presentation and polish.

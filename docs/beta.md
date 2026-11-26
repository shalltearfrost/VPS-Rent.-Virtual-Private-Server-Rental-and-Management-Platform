Andrii Moroz Â· Artem Ankudinov Â· Illia Yerokhin

# VPS Rent â€” Beta submission

VPS Rent is a Linux VPS rental and management application built with FastAPI,
SQLAlchemy and PostgreSQL. Customers order an existing plan, complete a test
payment, receive an operator-assigned server, request operations, renew their
rental and contact support. Staff have separate operator, support and plan
manager accounts. The frontend is integrated HTML, CSS and JavaScript.

The coursework scope is VPS rental. Minecraft hosting, game-server management,
proxy services, domain sales and supplier purchasing are not implemented
product features.

## Stage 1 requirements status

"Implemented" means implemented for the specified manual infrastructure and
test-payment product. It does not mean production hosting or real acquiring.

| ID | Functional requirement | Status | Implementation and validation |
| --- | --- | --- | --- |
| FR-01 | Accounts | Implemented | Unique normalized email, Argon2 password hash, login and logout; registration rejects role fields and always creates a customer. Session revocation and duplicate email tests. |
| FR-02 | Access control | Implemented | Backend role dependencies and ownership checks protect orders, invoices, rentals and tickets. Wrong role returns 403; another customer's record returns 404. Anonymous requests return 401. Role matrix and isolation tests. |
| FR-03 | Rental plans | Implemented | Public active catalogue; manager create/update/disable; positive resource and price checks. Existing order and renewal snapshots survive edits. |
| FR-04 | Orders | Implemented | Active-plan order creates an immutable configuration/price snapshot and invoice in one transaction, initially Awaiting Payment. Monthly and approved annual terms are supported. |
| FR-05 | Test payments | Implemented | Failure preserves state; success pays the invoice and queues allocation. Idempotency and database uniqueness prevent duplicate fulfillment. Monobank sandbox hosted payments, saved cards and automatic renewal validate signed events and stored UAH charge quotes; ambiguous attempts block retries; refunds await bank confirmation. |
| FR-06 | Server allocation | Implemented | Operator assigns an available server with matching CPU/RAM/disk. Transactions, row locks and a partial unique index prevent double allocation. Unmatched orders remain queued. |
| FR-07 | Server details | Implemented | Owner sees address, SSH instructions, configuration, power/rental state and expiry. Monthly rental starts at allocation and lasts 30 days. Password disclosure is authenticated, owner-only, audited and uncached. |
| FR-08 | Operation requests | Implemented | Active customers request start/stop/restart. Operator completes with a result or rejects with a reason. Power changes on completion. Locked state is refreshed so competing resolutions produce one success, one 409 and one history record. |
| FR-09 | Renewals | Implemented | An eligible renewal invoice uses the original monthly price. Success before expiry extends the existing expiry by exactly 30 days. Failed, duplicate and concurrent confirmations do not extend it twice. |
| FR-10 | Rental expiration | Implemented | Periodic scan flags overdue rentals. Operator confirms suspension, then preparation with changed credential data before reuse. Expired access and early preparation are refused. |
| FR-11 | Technical support | Implemented | Customer creates a ticket and exchanges messages with support. Support manages Open, In Progress and Closed. Customer isolation and separation from operator/manager privileges are enforced. |
| FR-12 | Activity history | Implemented | Allocations, operation requests/results, renewals, expiry, suspension/preparation and ticket status changes record actor, time, action and result. System actions use a null actor displayed as System. Staff history views are role-filtered. |

## Beta deliverables

| Deliverable | Repository evidence |
| --- | --- |
| Full team names at the start | README and this submission |
| Core application | `app/`, integrated role-specific frontend, regression tests |
| Complete PostgreSQL model | [Design](database.md), [full diagram](database.mmd), [DDL](schema.sql), Alembic migrations |
| Authentication | `app/security.py`, session routes in `app/api.py` |
| Authorization and roles | Backend dependencies, ownership checks, negative access tests |
| Integrated frontend | `app/static/`, same-origin API requests and database-backed state |
| Requirements status | FR-01 through FR-12 above |
| Alpha problems and resolutions | Table below |
| Updated team contribution statement | [Team ownership and contributions](team.md) |

## Alpha review problems and resolutions

This table records the issues and risks verified when taking the Alpha
implementation through the Beta review.

| Problem or risk | Resolution in the current Beta | Evidence |
| --- | --- | --- |
| Competing operators could both resolve one operation because SQLAlchemy retained a stale Pending object after waiting for a lock. | Refresh the operation using `populate_existing=True` after acquiring its row lock. Preserve the committed winner's result and power state. | Two synchronized HTTP regression cases: completion/completion and completion/rejection. One 200, one 409, one resolution history record. |
| Duplicate or concurrent payment notifications could fulfill or renew more than once. | Lock order/rental/invoice consistently; use idempotency keys and unique successful-payment indexes. | Initial-payment and concurrent renewal tests; signed Monobank callback replay tests. |
| One server could be allocated to competing paid orders. | Lock order and server, check matching resources and state, enforce one held rental with a partial unique index. | Concurrent allocation returns one 201 and one 409; the other order stays queued. |
| Plan edits could change a customer's existing purchase or renewal price. | Store plan configuration, initial price and monthly renewal price on the order. | Plan edit/disable snapshot regression. |
| Frontend-only restrictions would allow unauthorized API access. | Enforce roles and ownership in backend dependencies/services; validate CSRF on authenticated writes. | Four-role read matrix, foreign-resource tests, role escalation and CSRF tests. |
| Reusing a suspended server could expose the previous customer's credentials. | Keep it unavailable until operator preparation and require different encrypted credential data. | Expiry/suspension/preparation regression. The operator must perform actual provider preparation separately for real infrastructure. |
| Monobank EUR checkout did not provide a fixed UAH settlement quote. | Persist the exact UAH quote for the EUR invoice; validate amount, currency, reference, bank invoice and signature before fulfillment. | Quote retention, invalid-rate, forged-event and reconciliation tests; updated migration and ER model. |
| Alpha documentation did not provide a complete Beta status table or repeatable review procedure. | Add this matrix, issue resolutions, updated scope/contributions and a dedicated isolated review helper/guide. | `docs/beta.md`, `docs/beta-review.md`, `docs/team.md`, `scripts/beta_review.py`. |

## Data model and architecture

The complete model contains 14 application tables: users, sessions, plans,
orders, invoices, payments, payment cards, historical Monobank checkouts, servers, rentals, operation
requests, tickets, ticket messages and activity. PostgreSQL implements their
primary/foreign keys, uniqueness, checks and indexes. Alembic's version table
is additional technical metadata.

The model includes canonical payment attempts, saved charge quotes, encrypted saved-card tokens and a retained historical checkout ledger.
The updated [full ER diagram](database.mmd) includes these fields and links.
Business state transitions use transactions and row locks. Prices use integer
minor units; timestamps use timezone-aware UTC values. The [architecture
guide](architecture.md) traces requests and explains the permission matrix.

## Scope changes and infrastructure

The approved annual selector adds a 12-calendar-month initial term to the
original 30-day option. Renewals still extend by exactly 30 days. The monthly
path satisfies the original duration requirement. [The team document](team.md)
records this change and its reason.

The supplied Beta requirements demand a working application connected to real
PostgreSQL, not a paid fleet of VPS instances. The local review uses actual
PostgreSQL and persistent records. Seeded `192.0.2.0/24` addresses are example
inventory and cannot be used for SSH. Operators may enter already-provisioned
real instances for an optional infrastructure demonstration.

Allocation, power operations, suspension and preparation are manual workflows
from Stage 1. Confirming a result records the operator's action; the application
does not verify or execute a hypervisor/SSH operation. Test payments never
transfer real money. No real VPS or payment action should be claimed from the
example review data.

## Verification and remaining work

See the [review guide](beta-review.md) for reproducible role scenarios and the
[verification record](beta-verification.md) for executed checks and evidence.

No additional Stage 1 core feature is intentionally deferred. Final release
work includes deployment/HTTPS, UI polish, presentation preparation and
production hardening. Login throttling, account recovery/email verification,
pagination, monitored scheduling, secret management and backups are production
follow-ups outside the stated Beta feature list. Real acquiring, automatic VPS
provisioning and game hosting remain outside the coursework scope.

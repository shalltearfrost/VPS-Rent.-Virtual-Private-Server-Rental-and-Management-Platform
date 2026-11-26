Andrii Moroz Â· Artem Ankudinov Â· Illia Yerokhin

# Beta live review

Follow the main [README](../README.md) to install the locked dependencies,
configure `.env` and make PostgreSQL available. Run all commands below from the
repository root. The helper uses the same PostgreSQL credentials as `.env` but
targets the separate `vpsrent_monobank_sandbox_test` database when run with `--sandbox`. It never
resets or changes the normal application database.

## Prepare and start

```powershell
.venv/Scripts/python.exe -m scripts.beta_review prepare --sandbox --port 8002
.venv/Scripts/python.exe -m scripts.beta_review serve --sandbox --port 8002
```

Open [the review application](http://127.0.0.1:8002). Stop it with Ctrl+C.
Preparation is idempotent and preserves existing review records. The first run
creates the isolated database, applies all migrations and seeds three plans,
three documentation-address VPS records and four role accounts.

| Account | Role |
| --- | --- |
| customer@example.com | Customer |
| operator@example.com | Hosting operator |
| support@example.com | Support agent |
| manager@example.com | Plan manager |

The local review password for all four accounts is `Review-password-2026!`.
It is public test data for this localhost-only review, not a production
credential. Set `MONOBANK_TEST_TOKEN` in `.env` before preparation. The helper verifies a test merchant and uses the real bank sandbox. Without `--sandbox`, the helper uses `vpsrent_beta_review_test` with bank payments disabled; there are no manual payment-success endpoints.
Normal application accounts continue to use their existing credentials.

Sign out before switching roles. Tabs in the same browser profile share the
session cookie; use separate browser profiles if simultaneous sessions are
needed. OpenAPI is at `/docs`; database health is at `/api/health`.

## Customer and operator: order to allocated rental

1. As a visitor, compare CPU, RAM, disk and prices on the three-plan catalogue.
2. Register a separate customer, then sign out and sign back in. Alternatively,
   use the seeded customer for the rest of the demonstration.
3. Choose a plan and monthly term, then place an order. Show its saved
   configuration, unpaid invoice and Awaiting Payment status.
4. Choose Pay with monobank · Test. Enter synthetic card `4242424242424242`, future expiry and dummy CVV. Decline on the fake 3-D Secure screen; return and show that the order stays Awaiting Payment.
5. Retry and confirm on the fake 3-D Secure screen. Return and show a paid invoice and Waiting for allocation. Select Save card only when demonstrating optional automatic renewal.
6. Sign in as the operator. In Allocation, select a matching available VPS and
   assign it. An unavailable/unmatched order remains in the queue.
7. Sign in as the customer. My servers shows the assigned VPS, configuration,
   address, SSH command, status and expiry 30 days after allocation. Password
   disclosure is owner-only; it is example credential data in this review.
8. Refresh the browser to demonstrate that the result persists in PostgreSQL.

To demonstrate the no-capacity path, pay another order with the same resources
while the matching server is held. The operator sees a queued order with no
matching server. In Server pool, Add server can add another example record
using a unique name/address, matching resources and a test password.

## Customer and operator: operations

1. In an active customer's server panel, request Stop. Power must remain Running
   while the request is Pending. A second operation is refused while one waits.
2. As operator, open Operations, enter a result and Confirm completed. The
   customer then sees Stopped and the completed request.
3. Request Start, complete it as operator, and show Running again.
4. Request Restart, reject it with a reason, and show that power does not change.
5. Inspect operator History. The actor, timestamp, action and result persist.

The automated race regression covers two operators resolving one request
simultaneously: exactly one wins, the other receives HTTP 409. During this
review the results describe database fixtures, not actions on a real host.

## Customer: renewal

1. Open My servers and choose the active VPS.
2. Create its renewal invoice. Record the current expiry and renewal price.
3. Decline a hosted sandbox payment; verify expiry is unchanged.
4. Retry and confirm the hosted sandbox payment; verify expiry increases by
   exactly 30 days. Automated replay/concurrency tests verify no double extension.

## Customer and support: ticket lifecycle

1. As customer, create a ticket, optionally selecting the rented server.
2. As support, open the ticket, change Open to In Progress and send a reply.
3. As customer, read the reply and send a response.
4. As support, close the ticket. Closed tickets reject additional messages.
5. Inspect support History. It contains ticket events without operational or
   payment privileges. Server context excludes passwords.

## Plan manager

1. Sign in as manager and open Rental plans.
2. Create a temporary plan with positive resources and prices.
3. Edit its description/price and save. Verify it changes in the public catalogue.
4. Disable it; visitors cannot order it. Enable it again if needed.
5. Verify an existing customer's order retains its original resources and price.
   The automated snapshot test covers this invariant independently of the UI.

## Expiration, suspension and preparation

Use the rental ID shown in the customer's server URL. The following command
only changes the isolated review database's clock fixture; it is not a product
endpoint and cannot target the normal application database:

```powershell
.venv/Scripts/python.exe -m scripts.beta_review expire-rental --sandbox --id 1
```

Replace `1` with the review rental's ID. This marks an active rental overdue
and runs the same expiry service as the periodic worker. As operator, open
Server pool, confirm suspension, then confirm preparation with different test
credential data. The server must become Available only after preparation.
The former customer cannot reveal credentials, renew or request operations
after expiry. For real infrastructure, actual suspension and preparation must
be performed at the provider before confirming them.

## Backend refusal demonstration

- While signed in as operator, open `/api/management/plans`: HTTP 403.
- While signed in as support or manager, open `/api/operator/servers`: HTTP 403.
- While signed out, open `/api/orders`: HTTP 401.
- With a second customer account, request the first customer's order, invoice,
  rental or ticket URL: HTTP 404.
- Attempt to register with a `role` field: HTTP 422. A write request with an
  invalid/missing session CSRF token returns HTTP 403.

Use `/docs`, a terminal API client or browser developer tools for requests that
need a method/body. The browser menu is only presentation; backend refusal is
covered by the automated role and ownership tests.

## Explain the request flow

Trace a customer's Place order action from `app/static/app.js` to
`POST /api/orders`, Pydantic validation, session/CSRF/role dependencies,
`create_order`, PostgreSQL transaction, invoice creation and explicit response
presenters. Explain order snapshots, lock ordering, partial unique indexes and
why payments or allocation cannot be confirmed by frontend state alone.

Run the verification commands in the README before presenting. Current results
and browser evidence are recorded in [beta-verification.md](beta-verification.md).

## Payment reliability review

Saved test cards appear in the server panel. Choose a card or Off in Automatic
renewal. Removing a card clears consent for every rental that used it. An
unknown bank response displays Needs review and blocks another charge.
Refund pending remains distinct from Payment refunded.

The verified sandbox run is recorded in `beta-verification.md`. Signed webhook
replay, forged amounts, network ambiguity, concurrent dispatch and processing
refunds use deterministic transport fixtures; they are not real bank failures
induced against a live merchant. Public callback delivery needs an HTTPS origin.

# Monobank payment reliability

All gateway operations verify a test merchant before contacting a financial
endpoint. Live merchant tokens are rejected. A hosted page must use one of the
known Monobank HTTPS payment hosts. New payments freeze an explicit UAH quote
for the EUR invoice; settlement validates the stored amount, currency, provider
invoice, reference when supplied, and final amount before fulfilling a rental.

## Durable automatic renewal

The billing worker commits a Reserved payment, unique reference and amount
before dispatch. A second transaction locks that attempt and commits an
Uncertain marker before making the bank request. Competing dispatchers cannot
send the same attempt twice.

A definite bank rejection becomes Failed and can be retried after the configured
interval. A timeout, server error, malformed acknowledgment or process crash
leaves Uncertain, blocks a new charge and requires reconciliation. There is no
assumption that a missing response means no charge. A signed webhook can recover
the attempt by its persisted reference, validate its amount/currency, bind the
bank invoice ID and fulfill exactly once. If no reliable confirmation arrives,
the customer sees a review notice; the worker does not guess or retry.

## Refund lifecycle

A payment that cannot fulfill its invoice queues Refund Pending with a stable
refund reference. The queue is committed before a separate worker dispatches
the refund once. HTTP 200 with `status=processing` remains Refund Pending.
Only an authenticated successful refund response, a matching full cancellation
record, or a verified Reversed invoice completes the refund. Failed or ambiguous
refunds require review and are not reported as returned funds.

Reversed settled payments are flagged for review. Allocation is blocked while
a payment on that order needs review. Already assigned infrastructure remains
a manual operator responsibility.

## Verification

The regression suite covers mismatched signed amounts/currencies/final amounts,
unknown charge recovery, timeout and process-crash safety, competing dispatchers,
asynchronous refund completion and replay, live-token refusal, malformed events,
ownership and existing order/renewal workflows. Bank traffic in automated tests
uses `httpx.MockTransport`; PostgreSQL remains real.

Run `python -m alembic upgrade head` before starting the updated application.
The added migration preserves existing payments and adds explicit attempt and
refund states. Financial state is intentionally not downgraded automatically.

## Sandbox settlement currency

The live sandbox accepts EUR creation requests but converts the payment to UAH.
VPS Rent therefore quotes EUR prices with the official public EUR/UAH sell rate,
rounds half up to kopecks and saves the exact UAH charge before creating a page
or reserving an automatic charge. All later notifications must match that saved
amount and currency. A retry of an open invoice reuses its original quote.
The invoice remains denominated in EUR; card entry stays on the bank's page.

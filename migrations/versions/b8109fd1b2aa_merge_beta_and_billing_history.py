"""Merge billing with the Beta and preserve historical checkout records."""

from alembic import op

revision = "b8109fd1b2aa"
down_revision = ("19364610a068", "9a82d7d0d151")
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "UPDATE payments AS p SET provider = 'monobank', "
        "provider_invoice_id = c.provider_invoice_id, "
        "reference = c.reference, page_url = c.payment_url, "
        "charge_amount = c.amount_kopecks, "
        "charge_currency = CASE WHEN c.amount_kopecks IS NOT NULL "
        "THEN 'UAH' ELSE NULL END, "
        "review_required = c.review_required OR c.amount_kopecks IS NULL, "
        "provider_modified_at = c.modified_at "
        "FROM monobank_checkouts AS c WHERE c.payment_id = p.id"
    )
    op.execute(
        "INSERT INTO payments (invoice_id, customer_id, idempotency_key, "
        "status, provider, initiated_by, provider_invoice_id, page_url, "
        "save_card, reference, charge_amount, charge_currency, "
        "review_required, created_at, updated_at) "
        "SELECT c.invoice_id, o.customer_id, 'legacy-checkout-' || c.id, "
        "CASE WHEN c.status = 'success' OR c.amount_kopecks IS NULL "
        "THEN 'uncertain' ELSE 'pending' END, 'monobank', 'customer', "
        "c.provider_invoice_id, c.payment_url, false, c.reference, "
        "c.amount_kopecks, CASE WHEN c.amount_kopecks IS NOT NULL "
        "THEN 'UAH' ELSE NULL END, "
        "c.review_required OR c.amount_kopecks IS NULL "
        "OR c.status = 'success', c.created_at, now() "
        "FROM monobank_checkouts AS c "
        "JOIN invoices AS i ON i.id = c.invoice_id "
        "JOIN orders AS o ON o.id = i.order_id "
        "WHERE c.payment_id IS NULL AND c.status IN "
        "('created', 'processing', 'hold', 'success') "
        "AND NOT EXISTS (SELECT 1 FROM payments AS p "
        "WHERE p.provider_invoice_id = c.provider_invoice_id)"
    )
    op.execute(
        "UPDATE monobank_checkouts AS c SET payment_id = p.id "
        "FROM payments AS p WHERE c.payment_id IS NULL "
        "AND p.provider_invoice_id = c.provider_invoice_id"
    )


def downgrade():
    raise RuntimeError("Historical billing reconciliation is not reversible")

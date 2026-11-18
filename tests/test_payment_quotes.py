"""Regressions from the real Monobank sandbox conversion response."""

from decimal import Decimal

import httpx
import pytest

from app.billing.monobank import MonobankError
from tests.test_review_findings import replace_transport


def test_retry_keeps_the_original_uah_quote(clients, inventory, monobank):
    customer = clients["customer"]
    order = customer.post(
        "/api/orders",
        json={"plan_id": inventory[0].id, "term": "monthly"},
    ).json()
    invoice_id = order["invoices"][0]["id"]
    path = f"/api/invoices/{invoice_id}/payments"
    first = customer.post(
        path, json={"idempotency_key": "quote-first-attempt"}
    )
    assert first.status_code == 201
    assert first.json()["charge_amount"] == 8372
    assert first.json()["charge_currency"] == "UAH"
    monobank.gateway._rate = Decimal("55")
    repeated = customer.post(
        path, json={"idempotency_key": "quote-retry-attempt"}
    )
    assert repeated.json()["id"] == first.json()["id"]
    assert repeated.json()["charge_amount"] == 8372
    assert len(monobank.invoices) == 1
    monobank.finish()
    invoice = customer.get(f"/api/invoices/{invoice_id}").json()
    assert invoice["status"] == "paid"
    assert invoice["amount_cents"] == 169
    assert invoice["currency"] == "EUR"


@pytest.mark.parametrize("rate", [None, 0, -1, "NaN", "Infinity"])
def test_bad_fx_rate_never_creates_a_bank_invoice(monobank, rate):
    def bad_rate(request):
        if request.url.path == "/bank/currency":
            return httpx.Response(
                200,
                json=[
                    {
                        "currencyCodeA": 978,
                        "currencyCodeB": 980,
                        "rateSell": rate,
                    }
                ],
            )
        return monobank.handle(request)

    replace_transport(monobank, bad_rate)
    with pytest.raises(MonobankError, match="quote is unavailable"):
        monobank.gateway.quote(169, "EUR")
    assert not monobank.invoices

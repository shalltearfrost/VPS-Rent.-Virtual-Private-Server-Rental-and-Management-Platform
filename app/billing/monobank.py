"""Monobank acquiring client.

this module talks to Monobank. Services receive a ``Monobank`` instance
so tests can run it against ``httpx.MockTransport``.
"""

import base64
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from typing import Annotated

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from fastapi import Depends, HTTPException

from app.config import get_settings

# ISO 4217 numeric codes accepted as Monobank ``ccy``.
CURRENCY_CODES = {"EUR": 978, "USD": 840, "UAH": 980}
PENDING = {"created", "processing", "hold"}


class MonobankError(Exception):
    pass


@dataclass(frozen=True)
class InvoiceState:
    invoice_id: str
    status: str
    modified_at: datetime | None = None
    failure_reason: str | None = None
    card_token: str | None = None
    masked_pan: str | None = None
    page_url: str | None = None


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def currency_code(currency: str) -> int:
    try:
        return CURRENCY_CODES[currency]
    except KeyError as error:
        raise MonobankError(f"Unsupported currency {currency}") from error


class Monobank:
    def __init__(
        self,
        token: str,
        base_url: str = "https://api.monobank.ua",
        transport: httpx.BaseTransport | None = None,
    ):
        self.http = httpx.Client(
            base_url=base_url,
            headers={"X-Token": token},
            timeout=httpx.Timeout(15, connect=5),
            transport=transport,
        )
        self._public_key = None

    def _call(self, method: str, path: str, **kwargs) -> dict:
        try:
            response = self.http.request(method, path, **kwargs)
        except httpx.HTTPError as error:
            raise MonobankError("Monobank is unreachable") from error
        if response.status_code >= 400:
            try:
                detail = response.json()
                text = detail.get("errText") or detail.get("errorDescription")
            except ValueError:
                text = None
            raise MonobankError(
                text or f"Monobank returned HTTP {response.status_code}"
            )
        return response.json() if response.content else {}

    @staticmethod
    def parse_state(data: dict) -> InvoiceState:
        wallet = data.get("walletData") or {}
        payment = data.get("paymentInfo") or {}
        token = wallet.get("cardToken")
        if wallet.get("status") == "failed":
            token = None
        return InvoiceState(
            invoice_id=data["invoiceId"],
            status=data["status"],
            modified_at=parse_time(data.get("modifiedDate")),
            failure_reason=data.get("failureReason"),
            card_token=token,
            masked_pan=payment.get("maskedPan"),
        )

    def create_invoice(
        self,
        *,
        amount: int,
        currency: str,
        reference: str,
        destination: str,
        redirect_url: str,
        webhook_url: str | None,
        validity: int,
        wallet_id: str | None = None,
    ) -> InvoiceState:
        body = {
            "amount": amount,
            "ccy": currency_code(currency),
            "merchantPaymInfo": {
                "reference": reference,
                "destination": destination,
            },
            "redirectUrl": redirect_url,
            "validity": validity,
            "paymentType": "debit",
        }
        if webhook_url:
            body["webHookUrl"] = webhook_url
        if wallet_id:
            body["saveCardData"] = {"saveCard": True, "walletId": wallet_id}
        data = self._call("POST", "/api/merchant/invoice/create", json=body)
        return InvoiceState(
            invoice_id=data["invoiceId"],
            status="created",
            page_url=data["pageUrl"],
        )

    def invoice_status(self, invoice_id: str) -> InvoiceState:
        return self.parse_state(
            self._call(
                "GET",
                "/api/merchant/invoice/status",
                params={"invoiceId": invoice_id},
            )
        )

    def remove_invoice(self, invoice_id: str) -> None:
        self._call(
            "POST",
            "/api/merchant/invoice/remove",
            json={"invoiceId": invoice_id},
        )

    def refund(self, invoice_id: str) -> str:
        data = self._call(
            "POST",
            "/api/merchant/invoice/cancel",
            json={"invoiceId": invoice_id},
        )
        return data.get("status", "processing")

    def charge_card(
        self,
        *,
        card_token: str,
        amount: int,
        currency: str,
        reference: str,
        destination: str,
        webhook_url: str | None,
    ) -> InvoiceState:
        body = {
            "cardToken": card_token,
            "amount": amount,
            "ccy": currency_code(currency),
            "initiationKind": "merchant",
            "merchantPaymInfo": {
                "reference": reference,
                "destination": destination,
            },
            "paymentType": "debit",
        }
        if webhook_url:
            body["webHookUrl"] = webhook_url
        data = self._call("POST", "/api/merchant/wallet/payment", json=body)
        return InvoiceState(
            invoice_id=data["invoiceId"],
            status=data.get("status", "processing"),
            modified_at=parse_time(data.get("modifiedDate")),
            failure_reason=data.get("failureReason"),
        )

    def delete_card(self, card_token: str) -> None:
        self._call(
            "DELETE",
            "/api/merchant/wallet/card",
            params={"cardToken": card_token},
        )

    def _load_public_key(self):
        data = self._call("GET", "/api/merchant/pubkey")
        return load_pem_public_key(base64.b64decode(data["key"]))

    def verify_webhook(self, body: bytes, signature: str) -> bool:
        try:
            raw_signature = base64.b64decode(signature, validate=True)
        except ValueError:
            return False
        for attempt in range(2):
            # Monobank may rotate its key: reload once on mismatch.
            if self._public_key is None or attempt:
                self._public_key = self._load_public_key()
            try:
                self._public_key.verify(
                    raw_signature, body, ec.ECDSA(hashes.SHA256())
                )
                return True
            except InvalidSignature:
                continue
        return False


@lru_cache
def configured_gateway() -> Monobank | None:
    settings = get_settings()
    token = settings.monobank_token.get_secret_value().strip()
    if not token:
        return None
    return Monobank(token, settings.monobank_api_url)


def optional_gateway() -> Monobank | None:
    """FastAPI dependency; tests override it with a mock transport."""
    return configured_gateway()


def get_gateway(
    gateway: Annotated[Monobank | None, Depends(optional_gateway)],
) -> Monobank:
    if gateway is None:
        raise HTTPException(
            503, "Online payments are not configured (MONOBANK_TOKEN)"
        )
    return gateway

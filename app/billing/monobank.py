"""Sandbox-only Monobank acquiring client and validated bank responses."""

import base64
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Annotated, Literal
from urllib.parse import urlsplit

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from fastapi import Depends, HTTPException
from pydantic import AwareDatetime, BaseModel, Field, ValidationError

from app.config import get_settings

CURRENCY_CODES = {"EUR": 978, "USD": 840, "UAH": 980}
PENDING = {"created", "processing", "hold"}
PAYMENT_HOSTS = {"pay.mbnk.biz", "pay.monobank.ua"}


class MonobankError(Exception):
    def __init__(self, message: str, *, uncertain: bool = False):
        super().__init__(message)
        self.uncertain = uncertain


class BankPayload(BaseModel):
    invoice_id: str = Field(alias="invoiceId", min_length=1, max_length=64)
    status: Literal[
        "created",
        "processing",
        "hold",
        "success",
        "failure",
        "expired",
        "reversed",
    ]
    modified_at: AwareDatetime = Field(alias="modifiedDate")
    amount: int = Field(strict=True, gt=0)
    ccy: int = Field(strict=True)
    final_amount: int | None = Field(
        alias="finalAmount", default=None, strict=True, ge=0
    )
    reference: str | None = Field(default=None, min_length=1, max_length=64)


@dataclass(frozen=True)
class InvoiceState:
    invoice_id: str
    status: str
    modified_at: datetime | None = None
    failure_reason: str | None = None
    card_token: str | None = None
    masked_pan: str | None = None
    page_url: str | None = None
    amount: int | None = None
    ccy: int | None = None
    final_amount: int | None = None
    reference: str | None = None
    refunds: tuple[dict, ...] = ()


def currency_code(currency: str) -> int:
    try:
        return CURRENCY_CODES[currency]
    except KeyError as error:
        raise MonobankError(f"Unsupported currency {currency}") from error


def valid_payment_url(value) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parts = urlsplit(value)
        return (
            parts.scheme == "https"
            and parts.hostname in PAYMENT_HOSTS
            and not parts.username
            and not parts.password
            and parts.port in {None, 443}
        )
    except ValueError:
        return False


class Monobank:
    def __init__(
        self,
        token: str,
        base_url: str = "https://api.monobank.ua",
        transport: httpx.BaseTransport | None = None,
    ):
        if transport is None and base_url != "https://api.monobank.ua":
            raise ValueError("Use the official Monobank HTTPS API")
        self.http = httpx.Client(
            base_url=base_url,
            headers={"X-Token": token},
            timeout=httpx.Timeout(15, connect=5),
            transport=transport,
            trust_env=False,
            follow_redirects=False,
        )
        self._public_key = None
        self._sandbox_until = 0.0
        self._lock = threading.RLock()

    def _call(self, method: str, path: str, **kwargs) -> dict:
        try:
            response = self.http.request(method, path, **kwargs)
        except httpx.HTTPError as error:
            raise MonobankError(
                "Monobank confirmation is unavailable", uncertain=True
            ) from error
        if response.status_code >= 300:
            try:
                body = response.json()
                detail = body.get("errText") or body.get("errorDescription")
            except (ValueError, AttributeError):
                detail = None
            raise MonobankError(
                str(
                    detail or f"Monobank returned HTTP {response.status_code}"
                ),
                uncertain=(
                    response.status_code >= 500
                    or response.status_code in {408, 409, 429}
                ),
            )
        try:
            data = response.json() if response.content else {}
            if not isinstance(data, dict):
                raise ValueError("Expected an object")
            return data
        except ValueError as error:
            raise MonobankError(
                "Monobank returned an invalid response", uncertain=True
            ) from error

    def ensure_sandbox(self) -> None:
        with self._lock:
            if time.monotonic() < self._sandbox_until:
                return
            details = self._call("GET", "/api/merchant/details")
            if not str(details.get("merchantId", "")).startswith("test_"):
                raise MonobankError(
                    "A verified Monobank test token is required"
                )
            self._sandbox_until = time.monotonic() + 600

    @staticmethod
    def parse_state(data: dict) -> InvoiceState:
        try:
            value = BankPayload.model_validate(data)
            wallet = data.get("walletData") or {}
            payment = data.get("paymentInfo") or {}
            refunds = data.get("cancelList") or []
            if (
                not isinstance(wallet, dict)
                or not isinstance(payment, dict)
                or not isinstance(refunds, list)
                or any(not isinstance(item, dict) for item in refunds)
            ):
                raise ValueError("Invalid bank details")
            token = wallet.get("cardToken")
            if wallet.get("status") == "failed":
                token = None
            if token is not None and not isinstance(token, str):
                raise ValueError("Invalid card token")
            return InvoiceState(
                invoice_id=value.invoice_id,
                status=value.status,
                modified_at=value.modified_at,
                failure_reason=data.get("failureReason"),
                card_token=token,
                masked_pan=payment.get("maskedPan"),
                amount=value.amount,
                ccy=value.ccy,
                final_amount=value.final_amount,
                reference=value.reference,
                refunds=tuple(refunds),
            )
        except (ValidationError, ValueError, TypeError) as error:
            raise MonobankError(
                "Monobank returned an invalid payment state", uncertain=True
            ) from error

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
        self.ensure_sandbox()
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
        identifier = data.get("invoiceId")
        if (
            not isinstance(identifier, str)
            or not 1 <= len(identifier) <= 64
            or not valid_payment_url(data.get("pageUrl"))
        ):
            raise MonobankError("Monobank returned an invalid payment page")
        return InvoiceState(
            invoice_id=identifier,
            status="created",
            page_url=data["pageUrl"],
            amount=amount,
            ccy=currency_code(currency),
            reference=reference,
        )

    def invoice_status(self, invoice_id: str) -> InvoiceState:
        self.ensure_sandbox()
        return self.parse_state(
            self._call(
                "GET",
                "/api/merchant/invoice/status",
                params={"invoiceId": invoice_id},
            )
        )

    def remove_invoice(self, invoice_id: str) -> None:
        self.ensure_sandbox()
        self._call(
            "POST",
            "/api/merchant/invoice/remove",
            json={"invoiceId": invoice_id},
        )

    def refund(self, invoice_id: str, reference: str) -> str:
        self.ensure_sandbox()
        data = self._call(
            "POST",
            "/api/merchant/invoice/cancel",
            json={"invoiceId": invoice_id, "extRef": reference},
        )
        status = data.get("status")
        if status not in {"processing", "success", "failure"}:
            raise MonobankError("Invalid refund response", uncertain=True)
        return status

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
        self.ensure_sandbox()
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
        return self.parse_state(
            self._call("POST", "/api/merchant/wallet/payment", json=body)
        )

    def delete_card(self, card_token: str) -> None:
        self.ensure_sandbox()
        self._call(
            "DELETE",
            "/api/merchant/wallet/card",
            params={"cardToken": card_token},
        )

    def _load_public_key(self):
        self.ensure_sandbox()
        data = self._call("GET", "/api/merchant/pubkey")
        try:
            key = load_pem_public_key(
                base64.b64decode(data["key"], validate=True)
            )
            if not isinstance(key, ec.EllipticCurvePublicKey):
                raise ValueError("Expected ECDSA key")
            return key
        except (KeyError, ValueError, TypeError) as error:
            raise MonobankError("Invalid Monobank signing key") from error

    def verify_webhook(self, body: bytes, signature: str) -> bool:
        try:
            raw_signature = base64.b64decode(signature, validate=True)
        except (ValueError, TypeError):
            return False
        if not raw_signature or len(raw_signature) > 256:
            return False
        with self._lock:
            for attempt in range(2):
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
    return Monobank(token, settings.monobank_api_url) if token else None


def optional_gateway() -> Monobank | None:
    return configured_gateway()


def get_gateway(
    gateway: Annotated[Monobank | None, Depends(optional_gateway)],
) -> Monobank:
    if gateway is None:
        raise HTTPException(503, "Monobank test payments are not configured")
    return gateway

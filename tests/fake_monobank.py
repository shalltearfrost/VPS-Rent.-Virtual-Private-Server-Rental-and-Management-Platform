"""In-memory Monobank acquiring API served through httpx.MockTransport.

Only the network layer is replaced: the real ``app.billing.monobank.Monobank``
client builds requests and parses responses, so tests cover it too.
"""

import base64
import itertools
import json
from datetime import timedelta

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.billing.monobank import Monobank
from app.security import now


class FakeMonobank:
    def __init__(self):
        self.invoices: dict[str, dict] = {}
        self.requests: list[tuple[str, str, dict]] = []
        self.refunds: list[str] = []
        self.deleted_cards: list[str] = []
        self.charge_status = "success"
        self.charge_error: str | None = None
        self.create_error: str | None = None
        self._ids = itertools.count(1)
        # Starts in the past so tests can place bank events at "real" times.
        self._clock = now() - timedelta(hours=1)
        self._key = ec.generate_private_key(ec.SECP256R1())
        self.gateway = Monobank(
            "test-token",
            "https://mono.test",
            transport=httpx.MockTransport(self.handle),
        )

    # Helpers used by tests -------------------------------------------------
    @property
    def last_invoice_id(self) -> str:
        return list(self.invoices)[-1]

    def tick(self) -> str:
        self._clock += timedelta(seconds=1)
        return self._clock.isoformat()

    def finish(self, invoice_id=None, status="success", at=None) -> dict:
        invoice = self.invoices[invoice_id or self.last_invoice_id]
        invoice["status"] = status
        invoice["modifiedDate"] = at.isoformat() if at else self.tick()
        if status == "success":
            invoice["paymentInfo"] = {
                "maskedPan": "444403******1902",
                "paymentSystem": "visa",
                "paymentMethod": "pan",
                "terminal": "MI001",
            }
            if invoice["_wallet"]:
                invoice["walletData"] = {
                    "cardToken": f"card-token-{invoice['_wallet']}",
                    "walletId": invoice["_wallet"],
                    "status": "created",
                }
        if status == "failure":
            invoice["failureReason"] = "Card declined"
        return self.public(invoice)

    @staticmethod
    def public(invoice: dict) -> dict:
        return {k: v for k, v in invoice.items() if not k.startswith("_")}

    def sign(self, body: bytes) -> str:
        signature = self._key.sign(body, ec.ECDSA(hashes.SHA256()))
        return base64.b64encode(signature).decode()

    # Transport -------------------------------------------------------------
    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        path = request.url.path
        self.requests.append((request.method, path, body))
        if request.headers.get("X-Token") != "test-token":
            return httpx.Response(403, json={"errText": "forbidden"})
        if path == "/api/merchant/invoice/create":
            if self.create_error:
                return httpx.Response(400, json={"errText": self.create_error})
            invoice_id = f"mono-{next(self._ids)}"
            wallet = body.get("saveCardData", {}).get("walletId")
            self.invoices[invoice_id] = {
                "invoiceId": invoice_id,
                "status": "created",
                "amount": body["amount"],
                "ccy": body["ccy"],
                "reference": body["merchantPaymInfo"]["reference"],
                "createdDate": self.tick(),
                "modifiedDate": self._clock.isoformat(),
                "_wallet": wallet,
            }
            return httpx.Response(
                200,
                json={
                    "invoiceId": invoice_id,
                    "pageUrl": f"https://pay.mbnk.test/{invoice_id}",
                },
            )
        if path == "/api/merchant/invoice/status":
            invoice = self.invoices[request.url.params["invoiceId"]]
            return httpx.Response(200, json=self.public(invoice))
        if path == "/api/merchant/invoice/remove":
            self.finish(body["invoiceId"], "expired")
            return httpx.Response(200)
        if path == "/api/merchant/invoice/cancel":
            self.refunds.append(body["invoiceId"])
            self.finish(body["invoiceId"], "reversed")
            return httpx.Response(200, json={"status": "success"})
        if path == "/api/merchant/wallet/payment":
            if self.charge_error:
                return httpx.Response(400, json={"errText": self.charge_error})
            invoice_id = f"mono-{next(self._ids)}"
            self.invoices[invoice_id] = {
                "invoiceId": invoice_id,
                "status": "processing",
                "amount": body["amount"],
                "ccy": body["ccy"],
                "createdDate": self.tick(),
                "modifiedDate": self._clock.isoformat(),
                "_wallet": None,
                "_token": body["cardToken"],
            }
            state = self.finish(invoice_id, self.charge_status)
            return httpx.Response(200, json=state)
        if path == "/api/merchant/wallet/card":
            self.deleted_cards.append(request.url.params["cardToken"])
            return httpx.Response(200)
        if path == "/api/merchant/pubkey":
            pem = self._key.public_key().public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            return httpx.Response(
                200, json={"key": base64.b64encode(pem).decode()}
            )
        return httpx.Response(404, json={"errText": "not found"})

"""
Lock order everywhere: order -> rental -> invoice -> payment.
Current implementation uses monobank acquiring
"""

import logging
from datetime import timedelta
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.billing.monobank import (
    PENDING,
    InvoiceState,
    Monobank,
    MonobankError,
)
from app.billing.schemas import PaymentInput
from app.config import get_settings
from app.models import Invoice, Order, Payment, PaymentCard, Rental, User
from app.security import decrypt_password, encrypt_password, now, token_hash
from app.services import owned_order, owned_rental, record, require_active

logger = logging.getLogger(__name__)
RENEWAL_DAYS = 30


def _lock(db: Session, model, record_id: int, *, skip_locked=False):
    return db.scalar(
        select(model)
        .where(model.id == record_id)
        .with_for_update(skip_locked=skip_locked)
        .execution_options(populate_existing=True)
    )


def lock_invoice(
    db: Session, invoice_id: int, user: User | None
) -> tuple[Invoice, Order, Rental | None]:
    """Lock an invoice with its order and rental; customers see only theirs."""
    snapshot = db.get(Invoice, invoice_id)
    if not snapshot:
        raise HTTPException(404, "Invoice not found")
    if user is not None:
        order = owned_order(db, snapshot.order_id, user, lock=True)
    else:
        order = _lock(db, Order, snapshot.order_id)
    rental = (
        _lock(db, Rental, snapshot.rental_id) if snapshot.rental_id else None
    )
    return _lock(db, Invoice, invoice_id), order, rental


def lock_payment(db: Session, payment_id: int):
    snapshot = db.get(Payment, payment_id)
    invoice, order, rental = lock_invoice(db, snapshot.invoice_id, None)
    return _lock(db, Payment, payment_id), invoice, order, rental


def pending_payment(db: Session, invoice: Invoice) -> Payment | None:
    return db.scalar(
        select(Payment).where(
            Payment.invoice_id == invoice.id, Payment.status == "pending"
        )
    )


def successful_payment(db: Session, invoice: Invoice) -> Payment | None:
    return db.scalar(
        select(Payment).where(
            Payment.invoice_id == invoice.id, Payment.status == "succeeded"
        )
    )


def amount_label(invoice: Invoice) -> str:
    return f"{invoice.amount_cents / 100:.2f} {invoice.currency}"


def wallet_id(customer_id: int) -> str:
    return f"{get_settings().monobank_wallet_prefix}-{customer_id}"


def destination(invoice: Invoice, order: Order) -> str:
    kind = "renewal, 30 days" if invoice.kind == "renewal" else order.term
    return f"VPS Rent {order.plan_name} ({kind}), INV-{invoice.id:04d}"


def renewable_until(rental: Rental, at) -> bool:
    """A renewal payment is valid only if it completed before expiry."""
    return (
        rental.status in {"active", "suspension_pending"}
        and at < rental.expires_at
    )


def remember_card(
    db: Session, customer_id: int, token: str, masked_pan: str | None
) -> PaymentCard:
    digest = token_hash(token)
    card = db.scalar(
        select(PaymentCard).where(
            PaymentCard.token_hash == digest, PaymentCard.removed_at.is_(None)
        )
    )
    if card:
        return card
    card = PaymentCard(
        customer_id=customer_id,
        token_ciphertext=encrypt_password(token),
        token_hash=digest,
        masked_pan=masked_pan or "Saved card",
    )
    db.add(card)
    db.flush()
    return card


def _settle(
    db: Session,
    gateway: Monobank,
    payment: Payment,
    invoice: Invoice,
    order: Order,
    rental: Rental | None,
    paid_at,
) -> None:
    problem = None
    if invoice.status == "paid":
        problem = "The invoice was already paid"
    elif rental and not renewable_until(rental, paid_at):
        problem = "The rental expired before the payment completed"
    elif not rental and order.status != "awaiting_payment":
        problem = "The order no longer accepts payment"
    if problem:
        try:
            gateway.refund(payment.provider_invoice_id)
        except MonobankError as error:
            # Stay pending: the next synchronisation retries the refund.
            payment.failure_reason = f"{problem}; refund failed: {error}"
            logger.error("Refund failed for payment %s", payment.id)
            return
        payment.status = "refunded"
        payment.failure_reason = problem
        record(db, None, "payment_refunded", "invoice", invoice.id, problem)
        return
    payment.status = "succeeded"
    invoice.status = "paid"
    invoice.paid_at = paid_at
    if rental:
        if rental.status == "suspension_pending":
            # Paid before expiry, confirmed after the expiry scan ran.
            rental.status = "active"
            order.status = "active"
        rental.expires_at += timedelta(days=RENEWAL_DAYS)
        if payment.save_card and payment.card_id:
            rental.auto_renew_card_id = payment.card_id
        record(
            db,
            None,
            "rental_renewed",
            "rental",
            rental.id,
            f"Extended by {RENEWAL_DAYS} days until "
            f"{rental.expires_at:%Y-%m-%d}",
        )
    else:
        order.status = "awaiting_allocation"
    record(
        db,
        None,
        "payment_succeeded",
        "invoice",
        invoice.id,
        amount_label(invoice),
    )


def apply_state(
    db: Session,
    gateway: Monobank,
    locked: tuple[Payment, Invoice, Order, Rental | None],
    state: InvoiceState,
) -> Payment:
    """Apply a Monobank invoice state to a locked payment exactly once."""
    payment, invoice, order, rental = locked
    if (
        payment.provider_modified_at
        and state.modified_at
        and state.modified_at < payment.provider_modified_at
    ):
        return payment  # Out-of-order webhook: a newer state is applied.
    payment.updated_at = now()
    if state.modified_at:
        payment.provider_modified_at = state.modified_at
    if state.card_token and payment.save_card and not payment.card_id:
        card = remember_card(
            db, payment.customer_id, state.card_token, state.masked_pan
        )
        payment.card_id = card.id
    if payment.status == "pending":
        if state.status in PENDING:
            pass
        elif state.status == "success":
            _settle(
                db,
                gateway,
                payment,
                invoice,
                order,
                rental,
                state.modified_at or now(),
            )
        else:
            payment.status = "failed"
            payment.failure_reason = state.failure_reason or state.status
            action = (
                "auto_renewal_failed"
                if payment.initiated_by == "auto"
                else "payment_failed"
            )
            record(
                db, None, action, "invoice", invoice.id, payment.failure_reason
            )
    elif payment.status == "succeeded" and state.status == "reversed":
        payment.status = "refunded"
        payment.failure_reason = "Reversed by Monobank"
        record(db, None, "payment_reversed", "invoice", invoice.id, "Reversed")
    db.flush()
    return payment


def sync_payment(db: Session, gateway: Monobank, payment_id: int) -> Payment:
    locked = lock_payment(db, payment_id)
    payment = locked[0]
    if payment.status != "pending" or not payment.provider_invoice_id:
        return payment
    state = gateway.invoice_status(payment.provider_invoice_id)
    return apply_state(db, gateway, locked, state)


def handle_webhook(db: Session, gateway: Monobank, data: dict) -> None:
    state = Monobank.parse_state(data)
    payment_id = db.scalar(
        select(Payment.id).where(
            Payment.provider_invoice_id == state.invoice_id
        )
    )
    if payment_id is None:
        logger.warning("Webhook for unknown invoice %s", state.invoice_id)
        return
    apply_state(db, gateway, lock_payment(db, payment_id), state)


def start_payment(
    db: Session,
    gateway: Monobank,
    user: User,
    invoice_id: int,
    data: PaymentInput,
) -> Payment:
    """Create (or reuse) a Monobank hosted payment page for an invoice."""
    invoice, order, rental = lock_invoice(db, invoice_id, user)
    previous = db.scalar(
        select(Payment).where(Payment.idempotency_key == data.idempotency_key)
    )
    if previous:
        if (
            previous.customer_id != user.id
            or previous.invoice_id != invoice.id
        ):
            raise HTTPException(409, "Payment key has already been used")
        return previous
    if invoice.status == "paid":
        return successful_payment(db, invoice)
    current = pending_payment(db, invoice)
    if current:
        if current.initiated_by == "auto":
            raise HTTPException(
                409, "An automatic renewal payment is being processed"
            )
        try:
            state = gateway.invoice_status(current.provider_invoice_id)
        except MonobankError as error:
            raise HTTPException(502, str(error)) from error
        apply_state(db, gateway, (current, invoice, order, rental), state)
        if current.status == "pending":
            if current.save_card == data.save_card:
                return current
            # Different card choice: replace the unpaid Monobank page.
            try:
                gateway.remove_invoice(current.provider_invoice_id)
            except MonobankError as error:
                raise HTTPException(502, str(error)) from error
            current.status = "failed"
            current.failure_reason = "Replaced by a new payment page"
            db.flush()
        if invoice.status == "paid":
            return current
    settings = get_settings()
    validity = settings.payment_validity_seconds
    if rental:
        if rental.status != "active" or rental.expires_at <= now():
            raise HTTPException(409, "This rental is no longer active")
        # The bank page must close before the rental expires.
        remaining = int((rental.expires_at - now()).total_seconds()) - 60
        if remaining < 120:
            raise HTTPException(
                409, "The rental expires too soon to complete a payment"
            )
        validity = min(validity, remaining)
    elif order.status != "awaiting_payment":
        raise HTTPException(409, "This order cannot accept an initial payment")
    try:
        # Monobank charges the invoice currency directly (EUR, ccy 978).
        state = gateway.create_invoice(
            amount=invoice.amount_cents,
            currency=invoice.currency,
            reference=f"INV-{invoice.id:04d}-{data.idempotency_key[:12]}",
            destination=destination(invoice, order),
            redirect_url=f"{settings.public_url}/#invoice/{invoice.id}",
            webhook_url=settings.webhook_url,
            validity=validity,
            wallet_id=wallet_id(user.id) if data.save_card else None,
        )
    except MonobankError as error:
        raise HTTPException(502, str(error)) from error
    payment = Payment(
        invoice_id=invoice.id,
        customer_id=user.id,
        idempotency_key=data.idempotency_key,
        status="pending",
        provider="monobank",
        initiated_by="customer",
        provider_invoice_id=state.invoice_id,
        page_url=state.page_url,
        save_card=data.save_card,
    )
    db.add(payment)
    db.flush()
    record(
        db,
        user,
        "payment_started",
        "invoice",
        invoice.id,
        amount_label(invoice),
    )
    return payment


def refresh_invoice(
    db: Session, gateway: Monobank | None, user: User, invoice_id: int
) -> tuple[Invoice, Payment | None]:
    """Return an owned invoice, synchronising its pending payment first."""
    invoice, order, rental = lock_invoice(db, invoice_id, user)
    current = pending_payment(db, invoice)
    if current and gateway and current.provider_invoice_id:
        try:
            state = gateway.invoice_status(current.provider_invoice_id)
            apply_state(db, gateway, (current, invoice, order, rental), state)
        except MonobankError:
            logger.warning("Payment %s status check postponed", current.id)
    return invoice, latest_payment(db, invoice.id)


def latest_payment(db: Session, invoice_id: int) -> Payment | None:
    return db.scalar(
        select(Payment)
        .where(Payment.invoice_id == invoice_id)
        .order_by(Payment.id.desc())
        .limit(1)
    )


def renewal_invoice_for(db: Session, rental: Rental, order: Order) -> Invoice:
    invoice = db.scalar(
        select(Invoice).where(
            Invoice.rental_id == rental.id, Invoice.status == "unpaid"
        )
    )
    if not invoice:
        invoice = Invoice(
            order_id=order.id,
            rental_id=rental.id,
            kind="renewal",
            amount_cents=order.renewal_cents,
        )
        db.add(invoice)
        db.flush()
        record(
            db,
            None,
            "renewal_invoice",
            "rental",
            rental.id,
            f"INV-{invoice.id:04d}",
        )
    return invoice


def customer_renewal_invoice(
    db: Session, user: User, rental_id: int
) -> Invoice:
    rental, order = owned_rental(db, rental_id, user, lock=True)
    require_active(rental)
    return renewal_invoice_for(db, rental, order)


def active_card(db: Session, card_id: int, customer_id: int) -> PaymentCard:
    card = db.get(PaymentCard, card_id)
    if not card or card.customer_id != customer_id or card.removed_at:
        raise HTTPException(404, "Card not found")
    return card


def set_auto_renew(
    db: Session, rental: Rental, user: User, card_id: int | None
) -> None:
    if card_id is not None:
        if rental.status != "active" or rental.expires_at <= now():
            raise HTTPException(409, "This rental is no longer active")
        card = active_card(db, card_id, user.id)
        result = f"Enabled with {card.masked_pan}"
    else:
        result = "Disabled"
    if rental.auto_renew_card_id != card_id:
        rental.auto_renew_card_id = card_id
        record(db, user, "auto_renew", "rental", rental.id, result)
    db.flush()


def remove_card(
    db: Session, gateway: Monobank | None, user: User, card_id: int
) -> None:
    card = active_card(db, card_id, user.id)
    card.removed_at = now()
    for rental in db.scalars(
        select(Rental)
        .where(Rental.auto_renew_card_id == card.id)
        .with_for_update()
    ):
        rental.auto_renew_card_id = None
        record(db, user, "auto_renew", "rental", rental.id, "Card removed")
    if gateway:
        try:
            gateway.delete_card(decrypt_password(card.token_ciphertext))
        except MonobankError:
            logger.warning("Card %s was not deleted at Monobank", card.id)
    db.flush()


def due_auto_renewals(db: Session) -> list[int]:
    horizon = now() + timedelta(days=get_settings().auto_renew_days_before)
    return list(
        db.scalars(
            select(Rental.id)
            .where(
                Rental.status == "active",
                Rental.auto_renew_card_id.is_not(None),
                Rental.expires_at > now(),
                Rental.expires_at <= horizon,
            )
            .order_by(Rental.expires_at)
        )
    )


def auto_renew(db: Session, gateway: Monobank, rental_id: int) -> str:
    """Charge the saved card for one due rental. Returns what happened."""
    snapshot = db.get(Rental, rental_id)
    order = _lock(db, Order, snapshot.order_id, skip_locked=True)
    if not order:
        return "busy"
    rental = _lock(db, Rental, rental_id)
    horizon = now() + timedelta(days=get_settings().auto_renew_days_before)
    if (
        rental.status != "active"
        or not rental.auto_renew_card_id
        or not now() < rental.expires_at <= horizon
    ):
        return "not_due"
    card = db.get(PaymentCard, rental.auto_renew_card_id)
    if card.removed_at:
        rental.auto_renew_card_id = None
        return "card_removed"
    invoice = _lock(db, Invoice, renewal_invoice_for(db, rental, order).id)
    if pending_payment(db, invoice):
        return "pending"
    last = db.scalar(
        select(Payment)
        .where(
            Payment.invoice_id == invoice.id,
            Payment.initiated_by == "auto",
        )
        .order_by(Payment.id.desc())
        .limit(1)
    )
    retry = timedelta(hours=get_settings().auto_renew_retry_hours)
    if last and last.created_at > now() - retry:
        return "waiting_retry"
    payment = Payment(
        invoice_id=invoice.id,
        customer_id=order.customer_id,
        idempotency_key=f"auto-{uuid4().hex}",
        status="pending",
        provider="monobank",
        initiated_by="auto",
        card_id=card.id,
    )
    try:
        state = gateway.charge_card(
            card_token=decrypt_password(card.token_ciphertext),
            amount=invoice.amount_cents,
            currency=invoice.currency,
            reference=f"INV-{invoice.id:04d}-{payment.idempotency_key[5:17]}",
            destination=destination(invoice, order),
            webhook_url=get_settings().webhook_url,
        )
    except MonobankError as error:
        payment.status = "failed"
        payment.failure_reason = str(error)
        db.add(payment)
        db.flush()
        record(
            db, None, "auto_renewal_failed", "invoice", invoice.id, str(error)
        )
        return "failed"
    payment.provider_invoice_id = state.invoice_id
    db.add(payment)
    db.flush()
    record(
        db,
        None,
        "auto_renewal_charged",
        "rental",
        rental.id,
        f"{amount_label(invoice)} from {card.masked_pan}",
    )
    apply_state(db, gateway, (payment, invoice, order, rental), state)
    return payment.status


def stale_pending_payments(db: Session, older_than: int = 15) -> list[int]:
    return list(
        db.scalars(
            select(Payment.id)
            .where(
                Payment.status == "pending",
                Payment.provider_invoice_id.is_not(None),
                Payment.updated_at < now() - timedelta(seconds=older_than),
            )
            .order_by(Payment.updated_at)
            .limit(50)
        )
    )


def run_billing_cycle(engine, gateway: Monobank) -> None:
    """Poll pending payments and charge due auto-renewals.

    Webhooks make polling mostly redundant in production; locally
    (no https PUBLIC_URL) polling is the only status source.
    """
    with Session(engine, expire_on_commit=False) as db:
        with db.begin():
            payments = stale_pending_payments(db)
        for payment_id in payments:
            try:
                with db.begin():
                    sync_payment(db, gateway, payment_id)
            except Exception:
                logger.exception(
                    "Payment %s synchronisation failed", payment_id
                )
        with db.begin():
            rentals = due_auto_renewals(db)
        for rental_id in rentals:
            try:
                with db.begin():
                    auto_renew(db, gateway, rental_id)
            except Exception:
                logger.exception("Auto-renewal of rental %s failed", rental_id)

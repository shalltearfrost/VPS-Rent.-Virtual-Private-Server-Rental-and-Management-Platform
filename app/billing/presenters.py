from app.models import Payment, PaymentCard


def payment_view(payment: Payment | None) -> dict | None:
    if payment is None:
        return None
    reason = payment.failure_reason
    if reason and not reason.isascii():
        reason = "The bank declined this payment"
    return {
        "id": payment.id,
        "invoice_id": payment.invoice_id,
        "status": payment.status,
        "provider": payment.provider,
        "initiated_by": payment.initiated_by,
        "save_card": payment.save_card,
        # The hosted page is only useful while the payment is open.
        "page_url": payment.page_url if payment.status == "pending" else None,
        "failure_reason": reason,
        "review_required": payment.review_required,
        "charge_amount": payment.charge_amount,
        "charge_currency": payment.charge_currency,
        "created_at": payment.created_at,
    }


def card_view(card: PaymentCard) -> dict:
    return {
        "id": card.id,
        "masked_pan": card.masked_pan,
        "created_at": card.created_at,
    }

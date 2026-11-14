from pydantic import Field

from app.schemas import Input


class PaymentInput(Input):
    idempotency_key: str = Field(min_length=16, max_length=64)
    save_card: bool = False


class AutoRenewInput(Input):
    card_id: int | None = Field(default=None, gt=0)

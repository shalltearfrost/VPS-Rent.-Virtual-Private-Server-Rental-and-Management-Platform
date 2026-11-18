from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    ValidationInfo,
    field_validator,
)


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="after")
    @classmethod
    def clean_text(cls, value, info: ValidationInfo):
        if not isinstance(value, str) or info.field_name == "password":
            return value
        if not value.strip():
            raise ValueError("Must not be blank")
        return value.strip()


class Credentials(Input):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)


class PlanInput(Input):
    name: str = Field(min_length=1, max_length=40)
    description: str = Field(min_length=1, max_length=160)
    cpu: int = Field(ge=1, le=256)
    ram_gb: int = Field(ge=1, le=4096)
    disk_gb: int = Field(ge=1, le=100000)
    monthly_cents: int = Field(ge=1, le=10000000)
    annual_cents: int = Field(ge=1, le=120000000)
    enabled: bool = True


class OrderInput(Input):
    plan_id: int = Field(gt=0)
    term: Literal["monthly", "annual"]


class AllocationInput(Input):
    server_id: int = Field(gt=0)


class ServerInput(Input):
    name: str = Field(min_length=1, max_length=40)
    address: str
    cpu: int = Field(ge=1, le=256)
    ram_gb: int = Field(ge=1, le=4096)
    disk_gb: int = Field(ge=1, le=100000)
    ssh_user: str = Field(pattern=r"^[a-z_][a-z0-9_-]{0,31}$")
    password: str = Field(min_length=12, max_length=128)


class PreparationInput(Input):
    password: str = Field(min_length=12, max_length=128)


class OperationInput(Input):
    kind: Literal["start", "stop", "restart"]


class ResolutionInput(Input):
    status: Literal["completed", "rejected"]
    result: str = Field(min_length=1, max_length=2000)


class TicketInput(Input):
    subject: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1, max_length=5000)
    rental_id: int | None = Field(default=None, gt=0)


class MessageInput(Input):
    body: str = Field(min_length=1, max_length=5000)


class TicketStatusInput(Input):
    status: Literal["open", "in_progress", "closed"]

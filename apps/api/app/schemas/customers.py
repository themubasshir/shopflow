from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.schemas.sales import PaymentOut
from app.services.customer_phone import normalize_mobile

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
Money = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2)]


class CustomerUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: Name | None = None
    name_bn: Name | None = None
    phone: str | None = Field(default=None, min_length=1, max_length=40)
    email: str | None = Field(default=None, min_length=3, max_length=255)
    credit_limit: Money | None = None
    is_active: bool | None = None

    @field_validator("phone")
    @classmethod
    def valid_mobile(cls, value: str | None) -> str | None:
        return normalize_mobile(value) if value is not None else None

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str | None) -> str | None:
        if value is not None:
            parts = value.split("@")
            if (
                len(parts) != 2
                or not all(parts)
                or "." not in parts[1]
                or any(c.isspace() for c in value)
            ):
                raise ValueError("Enter a valid email address")
        return value

    @model_validator(mode="after")
    def reject_null_required_fields(self):
        for field in {"name", "phone", "credit_limit", "is_active"} & self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class CustomerCreate(CustomerUpdate):
    name: Name
    phone: str = Field(min_length=1, max_length=40)
    credit_limit: Money = Decimal(0)
    is_active: bool = True


class CustomerPaymentOut(PaymentOut):
    invoice_id: UUID
    invoice_number: str


class CustomerBalanceOut(BaseModel):
    outstanding_due: Decimal


class CustomerLedgerEntryOut(BaseModel):
    id: int
    invoice_id: UUID
    invoice_number: str
    return_id: UUID | None = None
    payment_id: UUID | None
    amount: Decimal
    balance_after: Decimal
    created_at: datetime


class DuePaymentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    method: Literal["cash", "bkash", "nagad"]
    reference: str | None = Field(default=None, max_length=120)


class DuePaymentOut(BaseModel):
    payment: CustomerPaymentOut
    outstanding_due: Decimal
    paid_total: Decimal
    due_total: Decimal
    payment_status: Literal["paid", "partially_paid", "due"]
    loyalty_points_earned: int
    idempotent_replay: bool = False


class LoyaltyEntryOut(BaseModel):
    id: UUID
    invoice_id: UUID | None
    invoice_number: str | None
    transaction_type: str
    points: int
    balance_after: int
    created_at: datetime


class CustomerLoyaltyOut(BaseModel):
    points_balance: int
    lifetime_earned: int
    lifetime_redeemed: int
    can_redeem: bool
    min_redeem_balance: int
    redeem_step_points: int
    point_value_bdt: Decimal

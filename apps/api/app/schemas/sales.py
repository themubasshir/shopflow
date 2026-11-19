from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, computed_field, field_validator, model_validator

from app.schemas.common import ORMModel


class CustomerOut(ORMModel):
    id: UUID
    name: str
    name_bn: str | None = None
    phone: str | None
    email: str | None
    credit_limit: Decimal
    points_balance: int = 0
    is_active: bool


class InvoiceItemOut(ORMModel):
    id: UUID
    product_id: UUID
    description: str
    quantity: Decimal
    unit_price: Decimal
    line_discount: Decimal
    line_total: Decimal


PaymentStatus = Literal["paid", "partially_paid", "due"]


def payment_status(paid: Decimal, due: Decimal) -> PaymentStatus:
    if due == 0:
        return "paid"
    return "partially_paid" if paid > 0 else "due"


class InvoiceBalance(ORMModel):
    paid_total: Decimal
    due_total: Decimal

    @computed_field
    @property
    def payment_status(self) -> PaymentStatus:
        return payment_status(self.paid_total, self.due_total)


class InvoiceOut(InvoiceBalance):
    id: UUID
    invoice_number: str
    counter_code: str | None = None
    customer_name: str | None = None
    status: str
    subtotal: Decimal
    discount_total: Decimal
    loyalty_discount: Decimal
    tax_total: Decimal
    total: Decimal
    finalized_at: datetime | None
    created_at: datetime
    items: list[InvoiceItemOut] = []
    payment_methods: list[str] = []


# --- Phase 2A: billing write path ------------------------------------------


class InvoiceItemCreate(BaseModel):
    """One cart line. Prices are NEVER accepted from the client — the server
    resolves the authoritative price from the product's sellable unit."""

    product_id: UUID
    product_unit_id: UUID | None = None
    quantity: Decimal = Field(gt=0, le=Decimal("999999.999"))
    # Per-line discount in BDT, applied by the cashier. Bounded server-side.
    line_discount: Decimal = Field(
        default=Decimal("0"), ge=0, le=Decimal("999999.99"), decimal_places=2
    )


class PaymentCreate(BaseModel):
    method: str = Field(pattern="^(cash|bkash|nagad)$")
    # Amount is optional; when omitted the payment covers the invoice total.
    amount: Decimal | None = Field(default=None, gt=0, le=Decimal("99999999.99"), decimal_places=2)
    reference: str | None = Field(default=None, max_length=120)


def _omit_default(schema: dict) -> None:
    # Keep new request fields optional in openapi-typescript clients.
    schema.pop("default", None)


class InvoiceCreate(BaseModel):
    counter_id: UUID
    customer_id: UUID | None = None
    items: list[InvoiceItemCreate] = Field(min_length=1, max_length=200)
    discount_total: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("999999.99"))
    payments: list[PaymentCreate] = Field(max_length=3)
    allow_due: bool = Field(
        default=False,
        description="Set to true to allow an unpaid amount for a registered customer.",
        json_schema_extra=_omit_default,
    )
    redeem_points: int = Field(
        default=0,
        ge=0,
        le=2147483647,
        description="Points to redeem in this sale. Omit for no redemption.",
        json_schema_extra=_omit_default,
    )

    @field_validator("items")
    @classmethod
    def quantity_step_ok(cls, items: list[InvoiceItemCreate]) -> list[InvoiceItemCreate]:
        for line in items:
            if line.quantity != line.quantity.quantize(Decimal("0.001")):
                raise ValueError("quantity supports at most 3 decimal places")
        return items

    @model_validator(mode="after")
    def payments_cover_total(self) -> InvoiceCreate:
        # Exact payment composition is validated again server-side once totals
        # are known; here we only guarantee well-formedness.
        supplied = [p for p in self.payments if p.amount is not None]
        if supplied and len(supplied) != len(self.payments):
            raise ValueError("either all payments carry an amount or none do")
        return self


class PaymentOut(ORMModel):
    id: UUID
    method: str
    amount: Decimal
    reference: str | None
    paid_at: datetime


class InvoiceCreateOut(InvoiceBalance):
    id: UUID
    invoice_number: str
    status: str
    counter_code: str
    customer_name: str | None
    subtotal: Decimal
    discount_total: Decimal
    tax_total: Decimal
    total: Decimal
    loyalty_discount: Decimal = Decimal("0.00")
    loyalty_points_redeemed: int = 0
    loyalty_points_earned: int
    loyalty_points_balance: int | None
    finalized_at: datetime | None
    items: list[InvoiceItemOut]
    payments: list[PaymentOut]
    idempotent_replay: bool = False

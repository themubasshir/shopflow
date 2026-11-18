from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.common import ORMModel


class CustomerOut(ORMModel):
    id: UUID
    name: str
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


class InvoiceOut(ORMModel):
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
    paid_total: Decimal
    due_total: Decimal
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
    line_discount: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("999999.99"))


class PaymentCreate(BaseModel):
    method: str = Field(pattern="^(cash|bkash|nagad)$")
    # Amount is optional; when omitted the payment covers the invoice total.
    amount: Decimal | None = Field(default=None, gt=0, le=Decimal("99999999.99"))
    reference: str | None = Field(default=None, max_length=120)


class InvoiceCreate(BaseModel):
    counter_id: UUID
    customer_id: UUID | None = None
    items: list[InvoiceItemCreate] = Field(min_length=1, max_length=200)
    discount_total: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("999999.99"))
    payments: list[PaymentCreate] = Field(min_length=1, max_length=3)

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


class InvoiceCreateOut(ORMModel):
    id: UUID
    invoice_number: str
    status: str
    counter_code: str
    customer_name: str | None
    subtotal: Decimal
    discount_total: Decimal
    tax_total: Decimal
    total: Decimal
    paid_total: Decimal
    due_total: Decimal
    loyalty_points_earned: int
    loyalty_points_balance: int | None
    finalized_at: datetime | None
    items: list[InvoiceItemOut]
    payments: list[PaymentOut]
    idempotent_replay: bool = False

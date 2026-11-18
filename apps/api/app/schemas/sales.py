from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

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

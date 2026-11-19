from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

ReconciliationArea = Literal[
    "invoice",
    "customer_due",
    "refund",
    "loyalty",
    "supplier",
    "product",
    "batch",
    "allocation",
    "lot",
    "valuation",
]


class Discrepancy(BaseModel):
    area: ReconciliationArea
    entity_id: UUID
    check: str
    expected: Decimal
    actual: Decimal


class ReconciliationOut(BaseModel):
    items: list[Discrepancy]
    total: int
    limit: int
    offset: int


class FinanceReport(BaseModel):
    start: date
    end: date
    gross_sales: Decimal
    discounts: Decimal
    customer_returns: Decimal
    net_sales: Decimal
    collections: Decimal
    refunds: Decimal
    pending_refunds: Decimal
    outstanding_dues: Decimal
    supplier_payables: Decimal
    supplier_credits: Decimal
    supplier_receivables: Decimal
    supplier_refunds: Decimal
    loyalty_issued: int
    loyalty_redeemed: int
    loyalty_reversed: int
    loyalty_restored: int

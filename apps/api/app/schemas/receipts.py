from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ReceiptLanguage = Literal["en", "bn", "bilingual"]


class ReceiptSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    shop_name_en: str = Field(min_length=1, max_length=160)
    shop_name_bn: str | None = Field(default=None, max_length=160)
    address: str | None = Field(default=None, max_length=400)
    phone: str | None = Field(default=None, max_length=40)
    trade_license: str | None = Field(default=None, max_length=64)
    tax_registration: str | None = Field(default=None, max_length=64)
    heading_en: str | None = Field(default=None, max_length=100)
    heading_bn: str | None = Field(default=None, max_length=100)
    footer_en: str | None = Field(default=None, max_length=500)
    footer_bn: str | None = Field(default=None, max_length=500)
    return_policy_en: str | None = Field(default=None, max_length=500)
    return_policy_bn: str | None = Field(default=None, max_length=500)
    preferred_language: ReceiptLanguage = "en"
    paper_width_mm: Literal[80] = 80
    printable_width_mm: int = Field(default=72, ge=58, le=76)


class ReceiptIdentity(BaseModel):
    branding: ReceiptSettings | None = None
    currency: str = "BDT"
    timezone: str = "Asia/Dhaka"
    counter_code: str | None = None
    counter_name_en: str | None = None
    counter_name_bn: str | None = None
    cashier: str | None = None
    customer_name: str | None = None
    customer_name_bn: str | None = None
    customer_phone_masked: str | None = None
    source: Literal["sale", "legacy_migration", "unavailable"] = "unavailable"


class ReceiptBatchAllocation(BaseModel):
    batch_number: str
    expiry_date: date
    quantity: Decimal


class ReceiptLineIdentity(BaseModel):
    name_bn: str | None = None
    unit_en: str | None = None
    unit_bn: str | None = None
    batch: str | None = None
    expiry: date | None = None
    batch_allocations: list[ReceiptBatchAllocation] = Field(default_factory=list)


class ReceiptLine(ReceiptLineIdentity):
    description: str
    quantity: Decimal
    unit_price: Decimal
    line_discount: Decimal
    line_total: Decimal


class ReceiptTender(BaseModel):
    method: str
    amount: Decimal


class InvoiceReceipt(BaseModel):
    id: UUID
    invoice_number: str
    issued_at: datetime | None
    status: Literal["finalized", "voided", "refunded"]
    voided_at: datetime | None
    identity: ReceiptIdentity
    items: list[ReceiptLine]
    subtotal: Decimal
    discount_total: Decimal
    loyalty_discount: Decimal
    tax_total: Decimal
    total: Decimal
    paid_total: Decimal
    due_total: Decimal
    payments: list[ReceiptTender]
    loyalty_points_redeemed: int
    loyalty_points_earned: int
    loyalty_points_balance: int | None

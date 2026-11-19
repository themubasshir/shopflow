from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.services.stock import MAX_MONEY, MAX_QUANTITY

Quantity = Annotated[Decimal, Field(gt=0, le=MAX_QUANTITY, decimal_places=3)]
Amount = Annotated[Decimal, Field(gt=0, le=MAX_MONEY, decimal_places=2)]
RefundMethod = Literal["cash", "bkash", "nagad"]
SupplierMethod = Literal["cash", "bkash", "nagad", "bank"]
Disposition = Literal["sellable", "quarantine", "damaged", "disposal", "supplier_staging"]
Reason = Annotated[str, Field(min_length=2, max_length=400)]
Reference = Annotated[str, Field(min_length=1, max_length=120)]


class ReturnSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invoice_item_id: UUID
    batch_id: UUID | None = None
    quantity: Quantity
    disposition: Disposition | None = None
    verified: bool = False


class ReturnWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    lines: list[ReturnSelection] = Field(min_length=1, max_length=200)
    reason: Reason
    refund_method: RefundMethod | None = None
    cash_reference: Reference | None = None


class RefundComplete(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    reference: Reference


class ReturnLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    invoice_item_id: UUID
    batch_id: UUID | None
    quantity: Decimal
    amount: Decimal
    disposition: Disposition
    verified: bool
    held: bool = False
    stock_traced: bool = False


class ReturnOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    invoice_id: UUID
    actor_id: UUID
    created_at: datetime
    reason: str
    amount: Decimal
    due_reduction: Decimal
    refund_amount: Decimal
    refund_method: RefundMethod | None
    earned_reversed: int
    redeemed_restored: int
    refund_status: Literal["none", "pending", "completed"] = "none"
    refund_reference: str | None = None
    refund_completed_at: datetime | None = None
    refund_actor_id: UUID | None = None
    lines: list[ReturnLineOut] = Field(default_factory=list)
    idempotent_replay: bool = False


class ReturnOption(BaseModel):
    invoice_item_id: UUID
    description: str
    name_bn: str | None
    base_unit: str
    batch_id: UUID | None
    batch_number: str | None
    expiry_date: date | None
    quantity: Decimal
    remaining: Decimal
    medicine: bool
    stock_traced: bool
    can_restore: bool


class InvoiceReturnsOut(BaseModel):
    invoice_id: UUID
    outstanding_due: Decimal
    rows: list[ReturnOption]
    history: list[ReturnOut]


class ResolveReturnStock(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    action: Literal["dispose", "supplier_return"]
    reason: Reason


class StockResolutionOut(BaseModel):
    line_id: UUID
    reference_id: UUID
    action: Literal["dispose", "supplier_return"]
    idempotent_replay: bool = False


class SupplierReturnLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lot_id: UUID
    quantity: Quantity


class SupplierReturnWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    lines: list[SupplierReturnLine] = Field(min_length=1, max_length=100)
    reason: Reason


class SupplierShipmentOut(BaseModel):
    id: UUID
    quantity: Decimal
    cost: Decimal
    credit_note_id: UUID | None = None
    idempotent_replay: bool = False


class CreditWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    shipment_id: UUID
    reference: Reference
    reason: Reason
    amount: Amount


class CreditApply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purchase_id: UUID
    amount: Amount


class SupplierRefundWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    method: SupplierMethod
    amount: Amount
    reference: Reference


class CreditEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    purchase_id: UUID
    created_at: datetime
    kind: str
    amount: Decimal
    method: str | None
    reference: str | None


class CreditNoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    purchase_id: UUID
    supplier_id: UUID
    shipment_id: UUID
    reference: str
    reason: str
    amount: Decimal
    created_at: datetime
    available: Decimal = Decimal(0)
    applied: Decimal = Decimal(0)
    refunded: Decimal = Decimal(0)
    entries: list[CreditEntryOut] = Field(default_factory=list)
    idempotent_replay: bool = False


class SupplierLotOut(BaseModel):
    lot_id: UUID
    product: str
    name_bn: str | None
    batch_number: str | None
    movable: Decimal


class PurchaseCreditsOut(BaseModel):
    payable: Decimal
    lots: list[SupplierLotOut]
    shipments: list[SupplierShipmentOut]
    notes: list[CreditNoteOut]

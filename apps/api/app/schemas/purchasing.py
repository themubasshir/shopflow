from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Money = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2)]
Quantity = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=3)]
ShortName = Annotated[str, StringConstraints(min_length=1, max_length=160)]
Tender = Literal["cash", "bkash", "nagad", "bank"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SupplierWrite(Input):
    name: ShortName
    name_bn: str | None = Field(default=None, max_length=160)
    phone: str | None = Field(default=None, max_length=32)
    address: str | None = Field(default=None, max_length=500)
    is_active: bool = True
    product_ids: list[UUID] = Field(default_factory=list, max_length=2000)


class SupplierOut(SupplierWrite):
    id: UUID
    balance: Decimal


class PurchaseLineWrite(Input):
    product_id: UUID
    product_unit_id: UUID | None = None
    quantity: Quantity
    unit_cost: Money
    batch_number: str | None = Field(default=None, min_length=1, max_length=64)
    manufacture_date: date | None = None
    expiry_date: date | None = None


class PurchaseWrite(Input):
    supplier_id: UUID
    supplier_invoice_number: str | None = Field(default=None, min_length=1, max_length=80)
    discount_total: Money = Decimal("0")
    items: list[PurchaseLineWrite] = Field(min_length=1, max_length=100)


class PurchaseLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_id: UUID
    product_unit_id: UUID | None
    quantity: Decimal
    product_name: str | None = None
    product_name_bn: str | None = None
    unit_name: str | None = None
    unit_name_bn: str | None = None
    ordered_base: Decimal | None
    received_base: Decimal
    unit_cost: Decimal
    line_total: Decimal
    net_total: Decimal | None
    batch_number: str | None
    manufacture_date: date | None
    expiry_date: date | None


class PurchaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    supplier_id: UUID
    purchase_number: str
    supplier_name: str | None = None
    supplier_name_bn: str | None = None
    supplier_invoice_number: str | None
    status: str
    subtotal: Decimal
    discount_total: Decimal
    total: Decimal
    received_total: Decimal
    paid_total: Decimal
    outstanding: Decimal = Decimal("0")
    items: list[PurchaseLineOut]


class ReceiveLine(Input):
    purchase_item_id: UUID
    quantity: Quantity


class ReceiveWrite(Input):
    items: list[ReceiveLine] = Field(min_length=1, max_length=100)


class SupplierPaymentWrite(Input):
    amount: Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=2)]
    method: Tender
    reference: str | None = Field(default=None, max_length=120)


class SupplierEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    purchase_id: UUID
    kind: str
    amount: Decimal
    method: str | None
    reference: str | None
    created_at: datetime


class Reason(Input):
    reason: str = Field(min_length=3, max_length=500)


class StockChange(Reason):
    product_id: UUID
    batch_id: UUID | None = None
    quantity: Quantity
    action: Literal["add", "remove", "damage", "dispose", "supplier_return"]
    unit_cost: Money | None = None


class BatchState(Reason):
    quarantined: bool


class BatchOut(BaseModel):
    id: UUID
    product_id: UUID
    supplier_id: UUID | None
    product_name: str
    product_name_bn: str
    batch_number: str
    expiry_date: date
    manufacture_date: date | None
    received_at: datetime | None
    quantity_received: Decimal
    quantity_on_hand: Decimal
    purchase_cost: Decimal | None
    price_reference: Decimal | None
    days_to_expiry: int
    status: str


class MovementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_id: UUID
    batch_id: UUID | None
    movement_type: str
    quantity: Decimal
    unit_cost: Decimal | None
    note: str | None
    reference_type: str | None
    reference_id: UUID | None
    created_at: datetime


class StockValue(BaseModel):
    product_id: UUID
    quantity_on_hand: Decimal
    available: Decimal
    ledger_quantity: Decimal
    value: Decimal
    unvalued_quantity: Decimal
    low_stock_threshold: Decimal


class ThresholdWrite(Input):
    quantity: Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=3)]

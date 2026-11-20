from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.schemas.common import ORMModel

Money = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2)]
Quantity = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=3)]


class CategoryOut(ORMModel):
    id: UUID
    name_en: str
    name_bn: str
    slug: str
    is_medicine: bool
    loyalty_eligible: bool
    product_count: int = 0


class ProductUnitOut(ORMModel):
    id: UUID
    name: str
    name_bn: str
    conversion_factor: Decimal
    selling_price: Decimal
    is_base: bool


class ProductOut(ORMModel):
    id: UUID
    sku: str
    barcode: str | None
    name_en: str
    name_bn: str
    unit: str
    is_medicine: bool
    is_active: bool
    stock_on_hand: Decimal
    low_stock_threshold: Decimal
    price: Decimal | None = None
    category_name_en: str | None = None
    category_name_bn: str | None = None
    loyalty_eligible: bool = True
    nearest_expiry: date | None = None


# --- Phase 2E-2: catalog management (write) -----------------------------------

_NAME = Annotated[str, StringConstraints(min_length=1, max_length=200)]
_SHORT = Annotated[str, StringConstraints(min_length=1, max_length=160)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CategoryWrite(Input):
    """Create or update a category. ``slug`` is the stable machine identifier."""

    name_en: _SHORT
    name_bn: _SHORT
    slug: Annotated[
        str,
        StringConstraints(min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9\-_]*$"),
    ]
    parent_id: UUID | None = None
    is_medicine: bool = False
    loyalty_eligible: bool = True
    sort_order: int = Field(default=0, ge=0, le=100000)
    is_active: bool = True


class CategoryManageOut(CategoryOut):
    parent_id: UUID | None = None
    is_active: bool = True
    sort_order: int = 0
    product_count: int = 0


class ProductUnitWrite(Input):
    """One sellable/ordering unit. Exactly one unit must be ``is_base`` and the
    base unit carries conversion_factor 1."""

    name: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    name_bn: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    conversion_factor: Quantity = Decimal("1")
    selling_price: Money
    is_base: bool = False


class MedicineWrite(Input):
    """Pharmacy catalogue fields kept on ``medicine_details`` (not batches)."""

    brand_name: _SHORT
    generic_name: _NAME
    manufacturer: str | None = Field(default=None, max_length=160)
    strength: str | None = Field(default=None, max_length=80)
    dosage_form: str | None = Field(default=None, max_length=80)
    pack_size: str | None = Field(default=None, max_length=80)
    mrp: Money | None = None
    purchase_cost: Money | None = None
    retail_price: Money | None = None
    supplier_price: Money | None = None
    prescription_required: bool = False


class ProductWrite(Input):
    """Create a product. Stock always starts at zero; physical stock only
    enters through receiving or an audited opening-stock flow."""

    category_id: UUID
    sku: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    barcode: str | None = Field(default=None, max_length=64)
    name_en: _NAME
    name_bn: _NAME
    search_aliases: list[Annotated[str, StringConstraints(min_length=1, max_length=160)]] = Field(
        default_factory=list, max_length=40
    )
    unit: Annotated[str, StringConstraints(min_length=1, max_length=16)] = "piece"
    pack_size: str | None = Field(default=None, max_length=64)
    is_medicine: bool = False
    loyalty_eligible: bool = True
    tax_rate: Annotated[Decimal, Field(ge=0, le=100, max_digits=5, decimal_places=2)] = Decimal("0")
    low_stock_threshold: Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=3)] = Decimal(
        "10"
    )
    units: list[ProductUnitWrite] = Field(min_length=1, max_length=12)
    medicine: MedicineWrite | None = None


class ProductUpdate(Input):
    """Edit a product's catalogue fields. Never touches ``stock_on_hand`` /
    ``held_quantity`` — those move only through the stock ledger."""

    category_id: UUID | None = None
    barcode: str | None = Field(default=None, max_length=64)
    name_en: _NAME | None = None
    name_bn: _NAME | None = None
    search_aliases: list[Annotated[str, StringConstraints(min_length=1, max_length=160)]] | None = (
        Field(default=None, max_length=40)
    )
    unit: Annotated[str, StringConstraints(min_length=1, max_length=16)] | None = None
    pack_size: str | None = Field(default=None, max_length=64)
    is_medicine: bool | None = None
    loyalty_eligible: bool | None = None
    tax_rate: Annotated[Decimal, Field(ge=0, le=100, max_digits=5, decimal_places=2)] | None = None
    low_stock_threshold: Annotated[
        Decimal, Field(ge=0, max_digits=12, decimal_places=3)
    ] | None = None
    units: list[ProductUnitWrite] | None = Field(default=None, min_length=1, max_length=12)
    medicine: MedicineWrite | None = None
    is_active: bool | None = None


class ProductDetailOut(ProductOut):
    category_id: UUID
    search_aliases: list[str] = []
    pack_size: str | None = None
    tax_rate: Decimal = Decimal("0")
    units: list[ProductUnitOut] = []
    medicine: MedicineWrite | None = None
    has_history: bool = False
    created_at: datetime | None = None


class ProductStateWrite(Input):
    is_active: bool


# --- Bulk import --------------------------------------------------------------


class ProductImportRowModel(Input):
    """A single normalized import row (the shape the parser produces)."""

    row: int = Field(ge=1)
    sku: str = Field(min_length=1, max_length=64)
    name_en: _NAME
    name_bn: _NAME
    barcode: str | None = Field(default=None, max_length=64)
    category_slug: str | None = Field(default=None, max_length=80)
    unit: str = Field(default="piece", max_length=16)
    selling_price: Money | None = None
    search_aliases: list[str] = Field(default_factory=list, max_length=40)
    is_medicine: bool = False
    brand_name: str | None = Field(default=None, max_length=160)
    generic_name: str | None = Field(default=None, max_length=200)
    manufacturer: str | None = Field(default=None, max_length=160)
    strength: str | None = Field(default=None, max_length=80)
    dosage_form: str | None = Field(default=None, max_length=80)
    pack_size: str | None = Field(default=None, max_length=80)
    mrp: Money | None = None
    purchase_cost: Money | None = None
    retail_price: Money | None = None
    supplier_price: Money | None = None
    prescription_required: bool = False


class ImportRowError(BaseModel):
    row: int
    field: str | None = None
    message: str


class ImportPreviewRow(BaseModel):
    """One parsed row with its classification and any validation errors."""

    row: int
    action: Literal["create", "duplicate", "invalid"]
    errors: list[ImportRowError] = []
    data: ProductImportRowModel | None = None
    duplicate_of: str | None = None  # sku / barcode / name match found


class ImportPreview(BaseModel):
    batch_id: UUID
    filename: str
    total_rows: int
    create_count: int
    duplicate_count: int
    invalid_count: int
    rows: list[ImportPreviewRow]
    categories_created: list[str] = []


class ImportCommitRow(Input):
    """An approved row to insert. ``approved`` rows are inserted; the rest are
    skipped. ``sku`` ties the decision back to the previewed row."""

    row: int | None = Field(default=None, ge=1)
    sku: str
    name_en: _NAME
    name_bn: _NAME
    barcode: str | None = None
    category_slug: str | None = None
    unit: str = "piece"
    selling_price: Money | None = None
    search_aliases: list[str] = Field(default_factory=list, max_length=40)
    is_medicine: bool = False
    brand_name: str | None = None
    generic_name: str | None = None
    manufacturer: str | None = None
    strength: str | None = None
    dosage_form: str | None = None
    pack_size: str | None = None
    mrp: Money | None = None
    purchase_cost: Money | None = None
    retail_price: Money | None = None
    supplier_price: Money | None = None
    prescription_required: bool = False


class ImportCommit(Input):
    """Approved rows from the preview. The server re-validates every row
    against the live catalog at commit time — the preview is advisory only."""

    rows: list[ImportCommitRow] = Field(max_length=5000)
    create_missing_categories: bool = False


class ImportResultRow(BaseModel):
    sku: str
    status: Literal["created", "skipped_duplicate", "error"]
    detail: str | None = None
    product_id: UUID | None = None


class ImportReport(BaseModel):
    created: int
    skipped: int
    errors: int
    results: list[ImportResultRow]
    categories_created: list[str] = []


class LowStockAlert(BaseModel):
    product_id: UUID
    sku: str
    name_en: str
    name_bn: str
    stock_on_hand: Decimal
    low_stock_threshold: Decimal
    category_name_en: str | None


class ExpiryAlert(BaseModel):
    batch_id: UUID
    product_id: UUID
    sku: str
    name_en: str
    name_bn: str
    batch_number: str
    expiry_date: date
    quantity_on_hand: Decimal
    days_to_expiry: int

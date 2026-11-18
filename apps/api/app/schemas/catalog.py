from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


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


class ProductImportRow(BaseModel):
    """CSV/Excel import schema for grocery and medicine catalog items.

    Generic importer — no MedEx scraping. `source` records provenance and
    `verified_at` starts as null: imported prices are never authoritative
    until someone verifies them.
    """

    sku: str = Field(max_length=64)
    name_en: str = Field(max_length=200)
    name_bn: str = Field(max_length=200)
    barcode: str | None = Field(default=None, max_length=64)
    category_slug: str | None = Field(default=None, max_length=80)
    unit: str = Field(default="piece", max_length=16)
    selling_price: Decimal | None = Field(default=None, ge=0)
    brand_name: str | None = Field(default=None, max_length=160)
    generic_name: str | None = Field(default=None, max_length=200)
    manufacturer: str | None = Field(default=None, max_length=160)
    strength: str | None = Field(default=None, max_length=80)
    dosage_form: str | None = Field(default=None, max_length=80)
    pack_size: str | None = Field(default=None, max_length=80)
    mrp: Decimal | None = Field(default=None, ge=0)
    purchase_cost: Decimal | None = Field(default=None, ge=0)
    retail_price: Decimal | None = Field(default=None, ge=0)
    prescription_required: bool = False
    is_discontinued: bool = False
    source: str = Field(default="csv-import", max_length=64)

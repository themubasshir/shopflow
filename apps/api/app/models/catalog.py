from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import UnitOfMeasure

MONEY = Numeric(14, 2)
QUANTITY = Numeric(12, 3)


class Category(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "categories"

    shop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE"), nullable=False
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id", ondelete="SET NULL")
    )
    name_en: Mapped[str] = mapped_column(String(100), nullable=False)
    name_bn: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    is_medicine: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    loyalty_eligible: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
        comment="Configures whether spend in this category earns loyalty points.",
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    products: Mapped[list[Product]] = relationship(back_populates="category")

    __table_args__ = (
        UniqueConstraint("shop_id", "slug", name="uq_categories_shop_id_slug"),
        CheckConstraint("slug <> ''", name="slug_not_blank"),
        Index("ix_categories_shop_id_is_medicine", "shop_id", "is_medicine"),
    )


class Product(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "products"

    shop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE"), nullable=False
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id", ondelete="RESTRICT"), nullable=False
    )
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    barcode: Mapped[str | None] = mapped_column(String(64))
    name_en: Mapped[str] = mapped_column(String(200), nullable=False)
    name_bn: Mapped[str] = mapped_column(String(200), nullable=False)
    search_aliases: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    unit: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=UnitOfMeasure.PIECE.value
    )
    pack_size: Mapped[str | None] = mapped_column(String(64))
    is_medicine: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    loyalty_eligible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, server_default="0")
    low_stock_threshold: Mapped[Decimal] = mapped_column(
        QUANTITY, nullable=False, server_default="10"
    )
    stock_on_hand: Mapped[Decimal] = mapped_column(
        QUANTITY,
        nullable=False,
        server_default="0",
        comment="Denormalised from stock_movements inside the same transaction.",
    )

    category: Mapped[Category] = relationship(back_populates="products")
    units: Mapped[list[ProductUnit]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    medicine: Mapped[MedicineDetail | None] = relationship(back_populates="product", uselist=False)
    batches: Mapped[list[MedicineBatch]] = relationship(back_populates="product")

    __table_args__ = (
        UniqueConstraint("shop_id", "sku", name="uq_products_shop_id_sku"),
        UniqueConstraint("shop_id", "barcode", name="uq_products_shop_id_barcode"),
        CheckConstraint("tax_rate >= 0 AND tax_rate <= 100", name="tax_rate_range"),
        CheckConstraint("low_stock_threshold >= 0", name="low_stock_threshold_non_negative"),
        CheckConstraint("stock_on_hand >= 0", name="stock_on_hand_non_negative"),
        Index("ix_products_shop_id_category_id", "shop_id", "category_id"),
        Index("ix_products_shop_id_is_active", "shop_id", "is_active"),
        Index("ix_products_name_en", "name_en"),
        Index("ix_products_name_bn", "name_bn"),
        Index("ix_products_search_aliases", "search_aliases", postgresql_using="gin"),
    )


class ProductUnit(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "product_units"

    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    name_bn: Mapped[str] = mapped_column(String(64), nullable=False)
    conversion_factor: Mapped[Decimal] = mapped_column(
        QUANTITY,
        nullable=False,
        server_default="1",
        comment="How many base units this unit contains.",
    )
    selling_price: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, comment="Retail price for this unit, in BDT."
    )
    is_base: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))

    product: Mapped[Product] = relationship(back_populates="units")

    __table_args__ = (
        UniqueConstraint("product_id", "name", name="uq_product_units_product_id_name"),
        CheckConstraint("conversion_factor > 0", name="conversion_factor_positive"),
        CheckConstraint("selling_price >= 0", name="selling_price_non_negative"),
        Index(
            "uq_product_units_one_base",
            "product_id",
            unique=True,
            postgresql_where=text("is_base"),
        ),
    )


class MedicineDetail(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "medicine_details"

    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    brand_name: Mapped[str] = mapped_column(String(160), nullable=False)
    generic_name: Mapped[str] = mapped_column(String(200), nullable=False)
    manufacturer: Mapped[str | None] = mapped_column(String(160))
    strength: Mapped[str | None] = mapped_column(String(80))
    dosage_form: Mapped[str | None] = mapped_column(String(80))
    pack_size: Mapped[str | None] = mapped_column(String(80))
    mrp: Mapped[Decimal | None] = mapped_column(MONEY)
    purchase_cost: Mapped[Decimal | None] = mapped_column(MONEY)
    retail_price: Mapped[Decimal | None] = mapped_column(MONEY)
    prescription_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    is_discontinued: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    source: Mapped[str | None] = mapped_column(
        String(64), comment="Where the catalog row came from (manual, csv-import, medex...)."
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        nullable=True, comment="Prices are only authoritative after verification."
    )

    product: Mapped[Product] = relationship(back_populates="medicine")

    __table_args__ = (
        CheckConstraint("mrp IS NULL OR mrp >= 0", name="mrp_non_negative"),
        CheckConstraint(
            "retail_price IS NULL OR retail_price >= 0", name="retail_price_non_negative"
        ),
        Index("ix_medicine_details_generic_name", "generic_name"),
    )


class MedicineBatch(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "medicine_batches"

    shop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="SET NULL")
    )
    batch_number: Mapped[str] = mapped_column(String(64), nullable=False)
    expiry_date: Mapped[date] = mapped_column(Date, nullable=False)
    quantity_received: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False, server_default="0")
    manufacture_date: Mapped[date | None] = mapped_column(Date)
    quarantined: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    quantity_on_hand: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False, server_default="0")
    purchase_cost: Mapped[Decimal | None] = mapped_column(MONEY)
    mrp: Mapped[Decimal | None] = mapped_column(MONEY)
    received_at: Mapped[datetime | None] = mapped_column()
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    product: Mapped[Product] = relationship(back_populates="batches")

    __table_args__ = (
        UniqueConstraint(
            "product_id",
            "batch_number",
            "expiry_date",
            name="uq_medicine_batches_product_id_batch_number_expiry_date",
        ),
        CheckConstraint("quantity_on_hand >= 0", name="quantity_on_hand_non_negative"),
        Index("ix_medicine_batches_shop_id_expiry_date", "shop_id", "expiry_date"),
        Index("ix_medicine_batches_product_id_expiry_date", "product_id", "expiry_date"),
        Index(
            "ix_batches_sellable",
            "product_id",
            "expiry_date",
            "id",
            postgresql_where=text("is_active AND NOT quarantined AND quantity_on_hand > 0"),
        ),
        CheckConstraint("quantity_received >= quantity_on_hand", name="received_projection"),
    )


class Supplier(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "suppliers"

    shop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    name_bn: Mapped[str | None] = mapped_column(String(160))
    contact_person: Mapped[str | None] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(Text)
    is_medicine_supplier: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    __table_args__ = (Index("ix_suppliers_shop_id_is_active", "shop_id", "is_active"),)

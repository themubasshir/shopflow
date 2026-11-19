from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.catalog import MONEY, QUANTITY, Product, ProductUnit, Supplier
from app.models.enums import PurchaseStatus


class StockMovement(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "stock_movements"

    shop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("medicine_batches.id", ondelete="SET NULL")
    )
    stock_lot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("stock_lots.id", ondelete="RESTRICT")
    )
    held: Mapped[bool] = mapped_column(server_default=text("false"))
    invoice_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("invoice_items.id"))
    source_movement_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("stock_movements.id"))
    counter_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("counters.id", ondelete="SET NULL")
    )
    movement_type: Mapped[str] = mapped_column(String(24), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(
        QUANTITY, nullable=False, comment="Signed: positive = stock in, negative = stock out."
    )
    unit_cost: Mapped[Decimal | None] = mapped_column(MONEY)
    reference_type: Mapped[str | None] = mapped_column(String(32))
    reference_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    __table_args__ = (
        CheckConstraint("quantity <> 0", name="quantity_non_zero"),
        CheckConstraint(
            "movement_type IN ("
            "'opening','purchase','sale','return','adjustment','damage','transfer'"
            ")",
            name="movement_type_valid",
        ),
        Index("ix_stock_movements_shop_id_created_at", "shop_id", "created_at"),
        Index("ix_stock_movements_product_id_created_at", "product_id", "created_at"),
        Index("ix_stock_movements_reference", "reference_type", "reference_id"),
    )


class Purchase(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "purchases"

    shop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE"), nullable=False
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False
    )
    purchase_number: Mapped[str] = mapped_column(String(40), nullable=False)
    supplier_invoice_number: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default=PurchaseStatus.DRAFT.value
    )
    subtotal: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="0")
    discount_total: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="0")
    total: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="0")
    received_total: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="0")
    paid_total: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="0")
    purchased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    supplier: Mapped[Supplier] = relationship(lazy="selectin")

    @property
    def supplier_name(self) -> str:
        return self.supplier.name

    @property
    def supplier_name_bn(self) -> str | None:
        return self.supplier.name_bn

    items: Mapped[list[PurchaseItem]] = relationship(
        back_populates="purchase", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("shop_id", "purchase_number", name="uq_purchases_shop_id_purchase_number"),
        CheckConstraint(
            "status IN ('draft','partially_received','received','voided','reversed')",
            name="status_valid",
        ),
        CheckConstraint("total >= 0 AND paid_total >= 0", name="totals_non_negative"),
        CheckConstraint("paid_total <= total", name="paid_not_above_total"),
        Index("ix_purchases_shop_id_purchased_at", "shop_id", "purchased_at"),
        Index(
            "uq_purchases_supplier_reference",
            "supplier_id",
            text("lower(btrim(supplier_invoice_number))"),
            unique=True,
            postgresql_where=text(
                "supplier_invoice_number IS NOT NULL AND status NOT IN ('voided','reversed')"
            ),
        ),
    )


class PurchaseItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "purchase_items"

    purchase_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchases.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    product_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("product_units.id", ondelete="RESTRICT")
    )
    conversion_factor: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False, server_default="1")
    ordered_base: Mapped[Decimal | None] = mapped_column(QUANTITY)
    received_base: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False, server_default="0")
    net_total: Mapped[Decimal | None] = mapped_column(MONEY)
    manufacture_date: Mapped[date | None] = mapped_column(Date)
    batch_number: Mapped[str | None] = mapped_column(String(64))
    expiry_date: Mapped[date | None] = mapped_column(Date)
    quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    line_total: Mapped[Decimal] = mapped_column(MONEY, nullable=False)

    product: Mapped[Product] = relationship(lazy="joined")
    ordering_unit: Mapped[ProductUnit | None] = relationship(lazy="joined")

    @property
    def product_name(self) -> str:
        return self.product.name_en

    @property
    def product_name_bn(self) -> str:
        return self.product.name_bn

    @property
    def unit_name(self) -> str | None:
        return self.ordering_unit.name if self.ordering_unit else None

    @property
    def unit_name_bn(self) -> str | None:
        return self.ordering_unit.name_bn if self.ordering_unit else None

    purchase: Mapped[Purchase] = relationship(back_populates="items")

    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_cost >= 0 AND line_total >= 0", name="amounts_non_negative"),
        Index("ix_purchase_items_purchase_id", "purchase_id"),
    )


class SupplierProduct(Base):
    __tablename__ = "supplier_products"

    supplier_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("suppliers.id", ondelete="RESTRICT"), primary_key=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), primary_key=True
    )


class StockLot(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "stock_lots"

    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), index=True
    )
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("medicine_batches.id", ondelete="RESTRICT")
    )
    purchase_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("purchase_items.id", ondelete="RESTRICT"), index=True
    )
    quantity_received: Mapped[Decimal] = mapped_column(QUANTITY)
    quantity_remaining: Mapped[Decimal] = mapped_column(QUANTITY)
    held_quantity: Mapped[Decimal] = mapped_column(QUANTITY, server_default="0")
    cost_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SupplierLedger(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "supplier_ledger"

    supplier_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("suppliers.id", ondelete="RESTRICT"), index=True
    )
    purchase_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("purchases.id", ondelete="RESTRICT"), index=True
    )
    credit_note_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("supplier_credit_notes.id"))
    kind: Mapped[str] = mapped_column(String(24))
    amount: Mapped[Decimal] = mapped_column(MONEY)
    method: Mapped[str | None] = mapped_column(String(16))
    reference: Mapped[str | None] = mapped_column(String(120))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InvoiceBatchAllocation(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "invoice_batch_allocations"

    invoice_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("invoice_items.id", ondelete="RESTRICT")
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("medicine_batches.id", ondelete="RESTRICT")
    )
    quantity: Mapped[Decimal] = mapped_column(QUANTITY)
    batch_number: Mapped[str] = mapped_column(String(64))
    expiry_date: Mapped[date] = mapped_column(Date)

    __table_args__ = (UniqueConstraint("invoice_item_id", "batch_id"),)

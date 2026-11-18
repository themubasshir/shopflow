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
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.catalog import MONEY, QUANTITY
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
        String(16), nullable=False, server_default=PurchaseStatus.DRAFT.value
    )
    subtotal: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="0")
    discount_total: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="0")
    total: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="0")
    paid_total: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="0")
    purchased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    items: Mapped[list[PurchaseItem]] = relationship(
        back_populates="purchase", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("shop_id", "purchase_number", name="uq_purchases_shop_id_purchase_number"),
        CheckConstraint("status IN ('draft','received','voided')", name="status_valid"),
        CheckConstraint("total >= 0 AND paid_total >= 0", name="totals_non_negative"),
        CheckConstraint("paid_total <= total", name="paid_not_above_total"),
        Index("ix_purchases_shop_id_purchased_at", "shop_id", "purchased_at"),
    )


class PurchaseItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "purchase_items"

    purchase_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchases.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    batch_number: Mapped[str | None] = mapped_column(String(64))
    expiry_date: Mapped[date | None] = mapped_column(Date)
    quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    line_total: Mapped[Decimal] = mapped_column(MONEY, nullable=False)

    purchase: Mapped[Purchase] = relationship(back_populates="items")

    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_cost >= 0 AND line_total >= 0", name="amounts_non_negative"),
        Index("ix_purchase_items_purchase_id", "purchase_id"),
    )

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin
from app.models.catalog import MONEY, QUANTITY


class CustomerReturn(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "customer_returns"

    invoice_id: Mapped[UUID] = mapped_column(ForeignKey("invoices.id"))
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("clock_timestamp()")
    )
    reason: Mapped[str] = mapped_column(String(400))
    amount: Mapped[Decimal] = mapped_column(MONEY)
    due_reduction: Mapped[Decimal] = mapped_column(MONEY)
    refund_amount: Mapped[Decimal] = mapped_column(MONEY)
    refund_method: Mapped[str | None] = mapped_column(String(16))
    cash_reference: Mapped[str | None] = mapped_column(String(120))
    eligible_value: Mapped[Decimal] = mapped_column(MONEY)
    earned_reversed: Mapped[int] = mapped_column(Integer)
    redemption_value: Mapped[Decimal] = mapped_column(MONEY)
    redeemed_restored: Mapped[int] = mapped_column(Integer)


class CustomerReturnLine(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "customer_return_lines"

    return_id: Mapped[UUID] = mapped_column(ForeignKey("customer_returns.id"))
    invoice_item_id: Mapped[UUID] = mapped_column(ForeignKey("invoice_items.id"))
    batch_id: Mapped[UUID | None] = mapped_column(ForeignKey("medicine_batches.id"))
    quantity: Mapped[Decimal] = mapped_column(QUANTITY)
    amount: Mapped[Decimal] = mapped_column(MONEY)
    disposition: Mapped[str] = mapped_column(String(24))
    verified: Mapped[bool] = mapped_column(Boolean)


class CustomerRefundSettlement(Base):
    __tablename__ = "customer_refund_settlements"

    return_id: Mapped[UUID] = mapped_column(ForeignKey("customer_returns.id"), primary_key=True)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    shop_id: Mapped[UUID] = mapped_column(ForeignKey("shops.id"))
    method: Mapped[str] = mapped_column(String(16))
    reference: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("clock_timestamp()")
    )


class ReturnStockPortion(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "return_stock_portions"

    line_id: Mapped[UUID] = mapped_column(ForeignKey("customer_return_lines.id"))
    source_movement_id: Mapped[UUID] = mapped_column(ForeignKey("stock_movements.id"))
    quantity: Mapped[Decimal] = mapped_column(QUANTITY)


class ReturnStockResolution(Base):
    __tablename__ = "return_stock_resolutions"

    portion_id: Mapped[UUID] = mapped_column(
        ForeignKey("return_stock_portions.id"), primary_key=True
    )
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(24))
    reason: Mapped[str] = mapped_column(String(400))
    reference_id: Mapped[UUID]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("clock_timestamp()")
    )


class SupplierCreditNote(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "supplier_credit_notes"

    purchase_id: Mapped[UUID] = mapped_column(ForeignKey("purchases.id"))
    supplier_id: Mapped[UUID] = mapped_column(ForeignKey("suppliers.id"))
    shipment_id: Mapped[UUID]
    reference: Mapped[str] = mapped_column(String(120))
    reason: Mapped[str] = mapped_column(String(400))
    amount: Mapped[Decimal] = mapped_column(MONEY)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("clock_timestamp()")
    )

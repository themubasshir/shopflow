from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.catalog import MONEY, QUANTITY, Product
from app.models.enums import InvoiceStatus, PaymentMethod  # noqa: F401

if TYPE_CHECKING:
    from app.models.loyalty import LoyaltyAccount


class Customer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "customers"

    shop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    name_bn: Mapped[str | None] = mapped_column(String(160))
    phone: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(Text)
    credit_limit: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    notes: Mapped[str | None] = mapped_column(Text)

    loyalty_account: Mapped[LoyaltyAccount | None] = relationship(
        back_populates="customer", uselist=False
    )
    invoices: Mapped[list[Invoice]] = relationship(back_populates="customer")

    __table_args__ = (
        UniqueConstraint("shop_id", "phone", name="uq_customers_shop_id_phone"),
        CheckConstraint("credit_limit >= 0", name="credit_limit_non_negative"),
        Index("ix_customers_shop_id_name", "shop_id", "name"),
    )


class Invoice(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "invoices"

    shop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE"), nullable=False
    )
    counter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("counters.id", ondelete="RESTRICT"), nullable=False
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="SET NULL")
    )
    invoice_number: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=InvoiceStatus.DRAFT.value
    )
    subtotal: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="0")
    discount_total: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="0")
    loyalty_discount: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="0")
    tax_total: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="0")
    total: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="0")
    paid_total: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="0")
    due_total: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="0")
    return_due_total: Mapped[Decimal] = mapped_column(MONEY, server_default="0")
    loyalty_points_earned: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    loyalty_points_redeemed: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    loyalty_rule_snapshot: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    receipt_identity: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    receipt_points_balance: Mapped[int | None] = mapped_column(Integer)
    loyalty_award_base: Mapped[Decimal | None] = mapped_column(MONEY)
    loyalty_earn_base: Mapped[Decimal | None] = mapped_column(MONEY)
    idempotency_key: Mapped[str | None] = mapped_column(String(120))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    items: Mapped[list[InvoiceItem]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan"
    )
    payments: Mapped[list[Payment]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan"
    )
    customer: Mapped[Customer | None] = relationship(back_populates="invoices")

    __table_args__ = (
        UniqueConstraint("shop_id", "invoice_number", name="uq_invoices_shop_id_invoice_number"),
        UniqueConstraint("shop_id", "idempotency_key", name="uq_invoices_shop_id_idempotency_key"),
        CheckConstraint("status IN ('draft','finalized','voided','refunded')", name="status_valid"),
        CheckConstraint(
            "subtotal >= 0 AND discount_total >= 0 AND loyalty_discount >= 0 "
            "AND tax_total >= 0 AND total >= 0 AND paid_total >= 0 AND due_total >= 0",
            name="totals_non_negative",
        ),
        CheckConstraint(
            "loyalty_points_earned >= 0 AND loyalty_points_redeemed >= 0",
            name="loyalty_points_non_negative",
        ),
        CheckConstraint(
            "loyalty_discount <= subtotal - discount_total + tax_total",
            name="loyalty_discount_within_total",
        ),
        CheckConstraint(
            "status <> 'finalized' OR paid_total + due_total + return_due_total = total",
            name="finalized_payment_totals",
        ),
        Index("ix_invoices_shop_id_status_finalized_at", "shop_id", "status", "finalized_at"),
        Index("ix_invoices_counter_id_finalized_at", "counter_id", "finalized_at"),
        Index("ix_invoices_customer_id", "customer_id"),
    )


class InvoiceItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "invoice_items"

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    product_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_units.id", ondelete="SET NULL")
    )
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("medicine_batches.id", ondelete="SET NULL")
    )
    receipt_details: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    description: Mapped[str] = mapped_column(String(240), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    line_discount: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="0")
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, server_default="0")
    line_total: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    loyalty_eligible_amount: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, server_default="0"
    )

    invoice: Mapped[Invoice] = relationship(back_populates="items")
    product: Mapped[Product] = relationship()

    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price >= 0 AND line_total >= 0", name="amounts_non_negative"),
        CheckConstraint(
            "line_discount >= 0 AND line_discount <= unit_price * quantity",
            name="discount_within_line",
        ),
        CheckConstraint("tax_rate >= 0 AND tax_rate <= 100", name="tax_rate_range"),
        CheckConstraint("loyalty_eligible_amount >= 0", name="loyalty_amount_non_negative"),
        CheckConstraint("loyalty_eligible_amount <= line_total", name="loyalty_within_line"),
        Index("ix_invoice_items_invoice_id", "invoice_id"),
        Index("ix_invoice_items_product_id", "product_id"),
    )


class Payment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "payments"

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False
    )
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    reference: Mapped[str | None] = mapped_column(String(120))
    received_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    paid_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    note: Mapped[str | None] = mapped_column(Text)

    invoice: Mapped[Invoice] = relationship(back_populates="payments")

    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("method IN ('cash','bkash','nagad','card','due')", name="method_valid"),
        Index("ix_payments_invoice_id", "invoice_id"),
        Index("ix_payments_method_paid_at", "method", "paid_at"),
    )


class CustomerLedgerEntry(Base):
    """A positive unpaid sale or a negative payment allocated to that invoice."""

    __tablename__ = "customer_ledger_entries"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), nullable=False)
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id"), nullable=False)
    payment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("payments.id"), unique=True)
    return_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("customer_returns.id"), unique=True
    )
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        CheckConstraint(
            "(payment_id IS NULL AND return_id IS NULL AND amount > 0) OR "
            "(num_nonnulls(payment_id, return_id) = 1 AND amount < 0)",
            name="amount_matches_type",
        ),
        Index("ix_customer_ledger_entries_customer_id_id", "customer_id", "id"),
        Index(
            "uq_customer_ledger_entries_invoice_charge",
            "invoice_id",
            unique=True,
            postgresql_where=text("payment_id IS NULL AND return_id IS NULL"),
        ),
    )

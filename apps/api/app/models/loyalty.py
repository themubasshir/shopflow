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
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.catalog import MONEY
from app.models.enums import LoyaltyTransactionType, RedemptionStatus  # noqa: F401

if TYPE_CHECKING:
    from app.models.sales import Customer


class LoyaltyAccount(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "loyalty_accounts"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    shop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE"), nullable=False
    )
    points_balance: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    lifetime_earned: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    lifetime_redeemed: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    opening_points: Mapped[int] = mapped_column(BigInteger, server_default="0")
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    customer: Mapped[Customer] = relationship(back_populates="loyalty_account")
    transactions: Mapped[list[LoyaltyTransaction]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "lifetime_earned >= 0 AND lifetime_redeemed >= 0",
            name="points_non_negative",
        ),
        CheckConstraint(
            "lifetime_earned - lifetime_redeemed = points_balance",
            name="lifetime_matches_balance",
        ),
        Index("ix_loyalty_accounts_shop_id", "shop_id"),
    )


class LoyaltyTransaction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "loyalty_transactions"

    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("loyalty_accounts.id", ondelete="CASCADE"), nullable=False
    )
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="SET NULL")
    )
    return_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customer_returns.id"))
    ledger_sequence: Mapped[int] = mapped_column(BigInteger, Identity())
    transaction_type: Mapped[str] = mapped_column(String(16), nullable=False)
    points: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="Signed points; positive earn, negative redeem/reverse."
    )
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    account: Mapped[LoyaltyAccount] = relationship(back_populates="transactions")

    __table_args__ = (
        CheckConstraint("points <> 0", name="points_non_zero"),
        CheckConstraint(
            "transaction_type IN ('earn','redeem','reverse','adjust','expire')",
            name="type_valid",
        ),
        CheckConstraint(
            "(transaction_type = 'earn' AND points > 0) OR "
            "(transaction_type IN ('redeem','reverse','expire') AND points < 0) OR "
            "transaction_type = 'adjust'",
            name="signed_points_match_type",
        ),
        Index(
            "uq_loyalty_transactions_original_invoice_type",
            "account_id",
            "invoice_id",
            "transaction_type",
            unique=True,
            postgresql_where=text("return_id IS NULL"),
        ),
        Index(
            "uq_loyalty_transactions_return_type",
            "return_id",
            "transaction_type",
            unique=True,
            postgresql_where=text("return_id IS NOT NULL"),
        ),
        Index("ix_loyalty_transactions_account_id_created_at", "account_id", "created_at"),
        Index(
            "ix_loyalty_transactions_invoice_id_ledger_sequence", "invoice_id", "ledger_sequence"
        ),
    )


class LoyaltyRule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "loyalty_rules"

    shop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    points_per_100_bdt: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    min_redeem_balance: Mapped[int] = mapped_column(Integer, nullable=False, server_default="300")
    redeem_step_points: Mapped[int] = mapped_column(Integer, nullable=False, server_default="100")
    point_value_bdt: Mapped[Decimal] = mapped_column(
        MONEY,
        nullable=False,
        server_default="1.00",
        comment="Discount in BDT for one redeemed point.",
    )
    earn_on_eligible_category_only: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("points_per_100_bdt > 0", name="points_per_100_positive"),
        CheckConstraint("min_redeem_balance >= 0", name="min_redeem_non_negative"),
        CheckConstraint("redeem_step_points > 0", name="redeem_step_positive"),
        CheckConstraint("point_value_bdt > 0", name="point_value_positive"),
        Index(
            "uq_loyalty_rules_one_active_per_shop",
            "shop_id",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )


class LoyaltyRedemption(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "loyalty_redemptions"

    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("loyalty_accounts.id", ondelete="RESTRICT"), nullable=False
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("invoices.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    points_redeemed: Mapped[int] = mapped_column(Integer, nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=RedemptionStatus.APPLIED.value
    )
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("points_redeemed > 0", name="points_positive"),
        CheckConstraint("points_redeemed % 100 = 0", name="points_multiple_of_step"),
        CheckConstraint("discount_amount > 0", name="discount_positive"),
        CheckConstraint("status IN ('applied','reversed')", name="status_valid"),
        Index("ix_loyalty_redemptions_account_id", "account_id"),
    )

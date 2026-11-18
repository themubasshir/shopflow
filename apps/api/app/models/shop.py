from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import Locale


class Shop(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "shops"

    name_en: Mapped[str] = mapped_column(String(160), nullable=False)
    name_bn: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    address: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(255))
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="BDT")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, server_default="Asia/Dhaka")
    receipt_header: Mapped[str | None] = mapped_column(Text)
    receipt_footer: Mapped[str | None] = mapped_column(Text)
    vat_number: Mapped[str | None] = mapped_column(String(64))
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    counters: Mapped[list[Counter]] = relationship(back_populates="shop")
    users: Mapped[list[User]] = relationship(back_populates="shop")

    __table_args__ = (
        CheckConstraint("char_length(currency) = 3", name="currency_iso3"),
        Index("ix_shops_is_active", "is_active"),
    )


class Counter(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "counters"

    shop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(16), nullable=False)
    name_en: Mapped[str] = mapped_column(String(80), nullable=False)
    name_bn: Mapped[str] = mapped_column(String(80), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    shop: Mapped[Shop] = relationship(back_populates="counters")

    __table_args__ = (
        UniqueConstraint("shop_id", "code", name="uq_counters_shop_id_code"),
        Index("ix_counters_shop_id_is_active", "shop_id", "is_active"),
    )


class Role(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "roles"

    shop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name_en: Mapped[str] = mapped_column(String(80), nullable=False)
    name_bn: Mapped[str] = mapped_column(String(80), nullable=False)
    permissions: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))

    __table_args__ = (
        UniqueConstraint("shop_id", "code", name="uq_roles_shop_id_code"),
        CheckConstraint("code <> ''", name="code_not_blank"),
    )


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    shop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE"), nullable=False
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32))
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    preferred_locale: Mapped[str] = mapped_column(
        String(5), nullable=False, server_default=Locale.EN.value
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    shop: Mapped[Shop] = relationship(back_populates="users")
    role: Mapped[Role] = relationship()

    __table_args__ = (
        UniqueConstraint("shop_id", "email", name="uq_users_shop_id_email"),
        UniqueConstraint("shop_id", "phone", name="uq_users_shop_id_phone"),
        CheckConstraint("preferred_locale IN ('en', 'bn')", name="preferred_locale_valid"),
        Index("ix_users_shop_id_is_active", "shop_id", "is_active"),
    )

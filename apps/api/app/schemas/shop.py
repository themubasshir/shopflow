from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import ORMModel


class ShopOut(ORMModel):
    id: UUID
    name_en: str
    name_bn: str
    slug: str
    currency: str
    timezone: str
    is_demo: bool
    counters: list[CounterOut] = []


class CounterOut(ORMModel):
    id: UUID
    code: str
    name_en: str
    name_bn: str
    is_active: bool


class CounterActivity(BaseModel):
    id: UUID
    code: str
    name_en: str
    name_bn: str
    active_cashier: str | None
    invoice_count: int
    total_sales: Decimal
    is_busy: bool


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class MeOut(ORMModel):
    id: UUID
    name: str
    email: str
    preferred_locale: str
    role: str
    permissions: list[str]


class RecentTransaction(BaseModel):
    id: UUID
    invoice_number: str
    counter_code: str
    customer_name: str | None
    total: Decimal
    method: str | None
    finalized_at: datetime | None
    status: str

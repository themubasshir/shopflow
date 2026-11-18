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


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


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
    assigned_counter_ids: list[str] | None = None
    is_demo: bool = False


class RecentTransaction(BaseModel):
    id: UUID
    invoice_number: str
    counter_code: str
    customer_name: str | None
    total: Decimal
    method: str | None
    finalized_at: datetime | None
    status: str


# --- Phase 2B: employee + counter management -------------------------------


class RoleOut(ORMModel):
    id: UUID
    code: str
    name_en: str
    name_bn: str


class EmployeeOut(ORMModel):
    id: UUID
    name: str
    email: str
    phone: str | None
    role_code: str
    role_name_en: str
    role_name_bn: str
    is_active: bool
    preferred_locale: str
    last_login_at: datetime | None
    assigned_counter_ids: list[UUID]
    created_at: datetime


class EmployeeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=32)
    role_id: UUID
    password: str = Field(min_length=8, max_length=128)
    preferred_locale: str = Field(default="en", pattern="^(en|bn)$")
    counter_ids: list[UUID] = Field(default_factory=list)


class EmployeeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    phone: str | None = Field(default=None, max_length=32)
    role_id: UUID | None = None
    preferred_locale: str | None = Field(default=None, pattern="^(en|bn)$")


class ResetPasswordRequest(BaseModel):
    new_password: str = Field(min_length=8, max_length=128)


class CounterAssignRequest(BaseModel):
    counter_ids: list[UUID] = Field(default_factory=list)


class CounterUpdate(BaseModel):
    is_active: bool
    name_en: str | None = Field(default=None, min_length=1, max_length=80)
    name_bn: str | None = Field(default=None, min_length=1, max_length=80)

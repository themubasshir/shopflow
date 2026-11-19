from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel

from app.schemas.catalog import ExpiryAlert, LowStockAlert
from app.schemas.shop import CounterActivity, RecentTransaction


class DashboardSummary(BaseModel):
    today_sales: Decimal
    invoice_count: int
    average_bill: Decimal
    low_stock_count: int
    expiring_soon_count: int
    active_counters: int
    is_demo: bool
    generated_at: datetime


class SalesPoint(BaseModel):
    bucket: date
    sales: Decimal
    invoice_count: int


class LoyaltyAccountOut(BaseModel):
    customer_id: UUID
    customer_name: str
    customer_name_bn: str | None = None
    phone: str | None
    points_balance: int
    lifetime_earned: int
    lifetime_redeemed: int
    can_redeem: bool


class DashboardResponse(BaseModel):
    summary: DashboardSummary
    counters: list[CounterActivity]
    sales_series: list[SalesPoint]
    recent_transactions: list[RecentTransaction]
    low_stock: list[LowStockAlert]
    expiring: list[ExpiryAlert]

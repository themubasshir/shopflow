from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_principal
from app.db.session import get_db
from app.models import (
    Counter,
    Invoice,
    MedicineBatch,
    Payment,
    Product,
    Shop,
)
from app.models.catalog import Category
from app.schemas.catalog import ExpiryAlert, LowStockAlert
from app.schemas.reports import DashboardResponse, DashboardSummary, SalesPoint
from app.schemas.shop import CounterActivity, RecentTransaction
from app.services.stock import available_stock, shop_date

router = APIRouter(prefix="/reports", tags=["reports"])

EXPIRY_WINDOW_DAYS = 90


@router.get("/dashboard", response_model=DashboardResponse)
def dashboard(
    principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> DashboardResponse:
    shop_id = principal.shop_id
    today = datetime.now(UTC).date()

    finalized = Invoice.status == "finalized"

    # Daily sales summary + average bill, always against finalized invoices only.
    today_sales, invoice_count = db.execute(
        select(func.coalesce(func.sum(Invoice.total), 0), func.count(Invoice.id)).where(
            Invoice.shop_id == shop_id,
            finalized,
            func.date(Invoice.finalized_at) == today,
        )
    ).one()
    invoice_count = int(invoice_count or 0)
    average_bill = (today_sales / invoice_count) if invoice_count else 0

    # Low stock and medicine expiry alerts.
    expiry_today = shop_date(db, shop_id)
    saleable = available_stock(expiry_today)
    low_stock_rows = db.execute(
        select(Product, Category.name_en, saleable)
        .join(Category, Product.category_id == Category.id)
        .where(
            Product.shop_id == shop_id,
            Product.is_active.is_(True),
            saleable <= Product.low_stock_threshold,
        )
        .order_by(saleable)
        .limit(8)
    ).all()

    expiry_cutoff = expiry_today + timedelta(days=EXPIRY_WINDOW_DAYS)
    expiring_rows = db.execute(
        select(MedicineBatch, Product)
        .join(Product, MedicineBatch.product_id == Product.id)
        .where(
            MedicineBatch.shop_id == shop_id,
            MedicineBatch.is_active.is_(True),
            MedicineBatch.quantity_on_hand > 0,
            MedicineBatch.expiry_date <= expiry_cutoff,
        )
        .order_by(MedicineBatch.expiry_date)
        .limit(8)
    ).all()

    # Three-counter activity.
    counter_rows = db.execute(
        select(
            Counter,
            func.count(Invoice.id).label("invoices"),
            func.coalesce(func.sum(Invoice.total), 0).label("sales"),
        )
        .outerjoin(
            Invoice,
            (Invoice.counter_id == Counter.id)
            & (Invoice.finalized_at.isnot(None))
            & (func.date(Invoice.finalized_at) == today)
            & (Invoice.status == "finalized"),
        )
        .where(Counter.shop_id == shop_id, Counter.is_active.is_(True))
        .group_by(Counter.id)
        .order_by(Counter.sort_order)
    ).all()

    counters = [
        CounterActivity(
            id=c.id,
            code=c.code,
            name_en=c.name_en,
            name_bn=c.name_bn,
            active_cashier=None if int(invoices) == 0 else "Demo cashier",
            invoice_count=int(invoices),
            total_sales=sales,
            is_busy=int(invoices) > 0,
        )
        for c, invoices, sales in counter_rows
    ]

    # Last 7 days of sales for the chart.
    series_rows = db.execute(
        select(
            func.date(Invoice.finalized_at).label("bucket"),
            func.coalesce(func.sum(Invoice.total), 0).label("sales"),
            func.count(Invoice.id).label("invoices"),
        )
        .where(Invoice.shop_id == shop_id, finalized)
        .group_by("bucket")
        .order_by("bucket")
        .limit(14)
    ).all()
    sales_series = [
        SalesPoint(bucket=r.bucket, sales=r.sales, invoice_count=int(r.invoices))
        for r in series_rows
    ]

    primary_payment = (
        select(Payment.method)
        .where(Payment.invoice_id == Invoice.id, Payment.method != "due")
        .order_by(Payment.amount.desc(), Payment.paid_at, Payment.id)
        .limit(1)
        .scalar_subquery()
    )
    recent_rows = db.execute(
        select(Invoice, primary_payment, Counter.code)
        .join(Counter, Invoice.counter_id == Counter.id)
        .where(Invoice.shop_id == shop_id)
        .order_by(Invoice.created_at.desc())
        .limit(6)
    ).all()
    recent = [
        RecentTransaction(
            id=i.id,
            invoice_number=i.invoice_number,
            counter_code=code,
            customer_name=None,
            total=i.total,
            method=method or ("due" if i.due_total > 0 else None),
            finalized_at=i.finalized_at,
            status=i.status,
        )
        for i, method, code in recent_rows
    ]

    is_demo = bool(db.scalar(select(Shop.is_demo).where(Shop.id == shop_id)))

    return DashboardResponse(
        summary=DashboardSummary(
            today_sales=today_sales,
            invoice_count=invoice_count,
            average_bill=average_bill,
            low_stock_count=len(low_stock_rows),
            expiring_soon_count=len(expiring_rows),
            active_counters=len(counters),
            is_demo=is_demo,
            generated_at=datetime.now(UTC),
        ),
        counters=counters,
        sales_series=sales_series,
        recent_transactions=recent,
        low_stock=[
            LowStockAlert(
                product_id=p.id,
                sku=p.sku,
                name_en=p.name_en,
                name_bn=p.name_bn,
                stock_on_hand=stock,
                low_stock_threshold=p.low_stock_threshold,
                category_name_en=cat,
            )
            for p, cat, stock in low_stock_rows
        ],
        expiring=[
            ExpiryAlert(
                batch_id=b.id,
                product_id=p.id,
                sku=p.sku,
                name_en=p.name_en,
                name_bn=p.name_bn,
                batch_number=b.batch_number,
                expiry_date=b.expiry_date,
                quantity_on_hand=b.quantity_on_hand,
                days_to_expiry=(b.expiry_date - expiry_today).days,
            )
            for b, p in expiring_rows
        ],
    )

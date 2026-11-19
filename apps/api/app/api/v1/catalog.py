from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_principal
from app.db.session import get_db
from app.models import Category, Product, ProductUnit
from app.schemas.catalog import CategoryOut, ProductOut
from app.schemas.common import Paginated

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get("/categories", response_model=list[CategoryOut])
def list_categories(
    principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> list[CategoryOut]:
    rows = db.execute(
        select(Category, func.count(Product.id).label("product_count"))
        .outerjoin(Product, Product.category_id == Category.id)
        .where(Category.shop_id == principal.shop_id, Category.is_active.is_(True))
        .group_by(Category.id)
        .order_by(Category.sort_order, Category.name_en)
    ).all()
    return [
        CategoryOut(
            id=c.id,
            name_en=c.name_en,
            name_bn=c.name_bn,
            slug=c.slug,
            is_medicine=c.is_medicine,
            loyalty_eligible=c.loyalty_eligible,
            product_count=int(count),
        )
        for c, count in rows
    ]


@router.get("/products", response_model=Paginated[ProductOut])
def list_products(
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
    q: str | None = Query(default=None, description="Name, alias or barcode"),
    category_id: str | None = Query(default=None),
    medicine_only: bool = False,
    low_stock_only: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Paginated[ProductOut]:
    stmt = (
        select(Product, Category)
        .join(Category, Product.category_id == Category.id)
        .where(Product.shop_id == principal.shop_id, Product.is_active.is_(True))
    )
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Product.name_en).like(like),
                func.lower(Product.name_bn).like(like),
                func.lower(Product.barcode).like(like),
                Product.search_aliases.any(func.lower(q)),
            )
        )
    if medicine_only:
        stmt = stmt.where(Product.is_medicine.is_(True))
    if low_stock_only:
        stmt = stmt.where(Product.stock_on_hand <= Product.low_stock_threshold)
    if category_id:
        stmt = stmt.where(Category.id == category_id)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(stmt.order_by(Product.name_en).limit(limit).offset(offset)).all()

    # Pull the base unit price for display.
    product_ids = [p.id for p, _ in rows]
    price_map = {}
    if product_ids:
        for unit in db.execute(
            select(ProductUnit).where(
                ProductUnit.product_id.in_(product_ids), ProductUnit.is_base.is_(True)
            )
        ).scalars():
            price_map[unit.product_id] = unit.selling_price

    items = [
        ProductOut(
            id=p.id,
            sku=p.sku,
            barcode=p.barcode,
            name_en=p.name_en,
            name_bn=p.name_bn,
            unit=p.unit,
            is_medicine=p.is_medicine,
            is_active=p.is_active,
            stock_on_hand=p.stock_on_hand,
            low_stock_threshold=p.low_stock_threshold,
            price=price_map.get(p.id),
            category_name_en=c.name_en,
            category_name_bn=c.name_bn,
            loyalty_eligible=p.loyalty_eligible and c.loyalty_eligible,
        )
        for p, c in rows
    ]
    return Paginated(items=items, total=total, limit=limit, offset=offset)

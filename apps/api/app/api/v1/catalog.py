from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_authenticated_principal, get_principal
from app.db.session import get_db
from app.models import Category, Product, ProductUnit
from app.schemas.catalog import (
    CategoryManageOut,
    CategoryOut,
    CategoryWrite,
    ImportCommit,
    ImportPreview,
    ImportReport,
    ProductDetailOut,
    ProductOut,
    ProductStateWrite,
    ProductUpdate,
    ProductWrite,
)
from app.schemas.common import Paginated
from app.services import catalog as catalog_service
from app.services.catalog import ImportParseError
from app.services.stock import available_stock, shop_date

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
    q: str | None = Query(default=None, description="Name, SKU, alias or barcode"),
    category_id: str | None = Query(default=None),
    medicine_only: bool = False,
    low_stock_only: bool = False,
    sellable: bool = False,
    view: str | None = Query(
        default=None,
        description="Catalog view: in_stock | out_of_stock | missing_price | medicine",
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Paginated[ProductOut]:
    saleable = available_stock(shop_date(db, principal.shop_id))
    stmt = (
        select(Product, Category, saleable)
        .join(Category, Product.category_id == Category.id)
        .where(Product.shop_id == principal.shop_id, Product.is_active.is_(True))
    )
    if q:
        like = f"%{q.lower()}%"
        alias = func.unnest(Product.search_aliases).table_valued("alias")
        stmt = stmt.where(
            or_(
                func.lower(Product.name_en).like(like),
                func.lower(Product.sku).like(like),
                func.lower(Product.name_bn).like(like),
                func.lower(Product.barcode).like(like),
                select(1).select_from(alias).where(func.lower(alias.column).like(like)).exists(),
            )
        )
    if medicine_only:
        stmt = stmt.where(Product.is_medicine.is_(True))
    if sellable:
        # Billing default: only products that can actually be sold — stock on
        # hand above zero AND a configured (non-zero) base sellable price.
        # Imported MedEx catalog rows (0 stock, 0 price) are excluded here but
        # remain visible in the catalog/purchasing searches.
        base_price = (
            select(ProductUnit.selling_price)
            .where(ProductUnit.product_id == Product.id, ProductUnit.is_base.is_(True))
            .scalar_subquery()
        )
        stmt = stmt.where(saleable > 0, func.coalesce(base_price, 0) > 0)
    if low_stock_only:
        stmt = stmt.where(saleable <= Product.low_stock_threshold)
    if view:
        base_price_sq = (
            select(ProductUnit.selling_price)
            .where(ProductUnit.product_id == Product.id, ProductUnit.is_base.is_(True))
            .scalar_subquery()
        )
        if view == "in_stock":
            stmt = stmt.where(saleable > 0)
        elif view == "out_of_stock":
            stmt = stmt.where(saleable <= 0)
        elif view == "missing_price":
            stmt = stmt.where(func.coalesce(base_price_sq, 0) <= 0)
        elif view == "medicine":
            stmt = stmt.where(Product.is_medicine.is_(True))
    if category_id:
        stmt = stmt.where(Category.id == category_id)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(stmt.order_by(Product.name_en).limit(limit).offset(offset)).all()

    # Pull the base unit price for display.
    product_ids = [p.id for p, _, _ in rows]
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
            stock_on_hand=stock,
            low_stock_threshold=p.low_stock_threshold,
            price=price_map.get(p.id),
            category_name_en=c.name_en,
            category_name_bn=c.name_bn,
            loyalty_eligible=p.loyalty_eligible and c.loyalty_eligible,
        )
        for p, c, stock in rows
    ]
    return Paginated(items=items, total=total, limit=limit, offset=offset)


# --- Phase 2E-2: catalog management (write) -----------------------------------


@router.get("/products/{product_id}", response_model=ProductDetailOut)
def get_product(
    product_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> ProductDetailOut:
    product = catalog_service.product_by_id(db, principal, product_id)
    return catalog_service._product_detail(db, product)


@router.post("/products", response_model=ProductDetailOut, status_code=201)
def create_product(
    body: ProductWrite,
    principal: Principal = Depends(get_authenticated_principal),
    db: Session = Depends(get_db),
) -> ProductDetailOut:
    return catalog_service.create_product(db, principal, body)


@router.put("/products/{product_id}", response_model=ProductDetailOut)
def update_product(
    product_id: uuid.UUID,
    body: ProductUpdate,
    principal: Principal = Depends(get_authenticated_principal),
    db: Session = Depends(get_db),
) -> ProductDetailOut:
    return catalog_service.update_product(db, principal, product_id, body)


@router.patch("/products/{product_id}/state", response_model=ProductDetailOut)
def set_product_state(
    product_id: uuid.UUID,
    body: ProductStateWrite,
    principal: Principal = Depends(get_authenticated_principal),
    db: Session = Depends(get_db),
) -> ProductDetailOut:
    return catalog_service.set_product_active(db, principal, product_id, body.is_active)


@router.delete("/products/{product_id}", status_code=204)
def delete_product(
    product_id: uuid.UUID,
    principal: Principal = Depends(get_authenticated_principal),
    db: Session = Depends(get_db),
) -> None:
    catalog_service.delete_product(db, principal, product_id)


# --- Category management ------------------------------------------------------


@router.get("/categories/manage", response_model=list[CategoryManageOut])
def list_categories_manage(
    principal: Principal = Depends(get_authenticated_principal),
    db: Session = Depends(get_db),
) -> list[CategoryManageOut]:
    principal.require("catalog:write")
    return catalog_service.list_managed_categories(db, principal)


@router.post("/categories", response_model=CategoryManageOut, status_code=201)
def create_category(
    body: CategoryWrite,
    principal: Principal = Depends(get_authenticated_principal),
    db: Session = Depends(get_db),
) -> CategoryManageOut:
    return catalog_service.save_category(db, principal, body)


@router.put("/categories/{category_id}", response_model=CategoryManageOut)
def update_category(
    category_id: uuid.UUID,
    body: CategoryWrite,
    principal: Principal = Depends(get_authenticated_principal),
    db: Session = Depends(get_db),
) -> CategoryManageOut:
    return catalog_service.save_category(db, principal, body, category_id)


@router.patch("/categories/{category_id}/state", response_model=CategoryManageOut)
def set_category_state(
    category_id: uuid.UUID,
    body: ProductStateWrite,
    principal: Principal = Depends(get_authenticated_principal),
    db: Session = Depends(get_db),
) -> CategoryManageOut:
    return catalog_service.set_category_active(db, principal, category_id, body.is_active)


@router.delete("/categories/{category_id}", status_code=204)
def delete_category(
    category_id: uuid.UUID,
    principal: Principal = Depends(get_authenticated_principal),
    db: Session = Depends(get_db),
) -> None:
    catalog_service.delete_category(db, principal, category_id)


# --- Bulk import --------------------------------------------------------------


@router.post("/imports/preview", response_model=ImportPreview)
async def import_preview(
    principal: Principal = Depends(get_authenticated_principal),
    db: Session = Depends(get_db),
    file: UploadFile = File(...),
) -> ImportPreview:
    principal.require("catalog:write")
    raw = await file.read()
    try:
        parsed = catalog_service.parse_import_file(file.filename or "", raw)
    except ImportParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    rows = catalog_service.preview_import_rows(db, principal, parsed)
    create_n = sum(1 for r in rows if r.action == "create")
    dup_n = sum(1 for r in rows if r.action == "duplicate")
    invalid_n = sum(1 for r in rows if r.action == "invalid")
    return ImportPreview(
        batch_id=uuid.uuid4(),
        filename=file.filename or "",
        total_rows=len(rows),
        create_count=create_n,
        duplicate_count=dup_n,
        invalid_count=invalid_n,
        rows=rows,
    )


@router.post("/imports/commit", response_model=ImportReport)
def import_commit(
    body: ImportCommit,
    principal: Principal = Depends(get_authenticated_principal),
    db: Session = Depends(get_db),
) -> ImportReport:
    return catalog_service.commit_import(db, principal, body)

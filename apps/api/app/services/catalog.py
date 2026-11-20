"""Catalog management service: products, categories, units, medicine details.

Phase 2E-2. All writes go through here so the invariants live in one place:

* Every product starts with ``stock_on_hand = 0``. Physical stock only ever
  moves through the stock ledger (``post_stock``) — these functions never touch
  ``stock_on_hand`` or ``held_quantity``.
* ``sku`` and ``barcode`` are unique per shop; edits re-check uniqueness.
* Exactly one ``ProductUnit`` per product is ``is_base`` with
  ``conversion_factor == 1``.
* Products with financial or inventory history are never hard-deleted — they
  are deactivated instead, preserving the invoice/receipt snapshots that
  billing already wrote.
* Every mutating call writes an ``AuditLog`` row in the same transaction.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import Principal
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.models import (
    Category,
    InvoiceItem,
    MedicineDetail,
    Product,
    ProductUnit,
    PurchaseItem,
    StockMovement,
)
from app.schemas.catalog import (
    CategoryManageOut,
    CategoryWrite,
    ImportCommit,
    ImportCommitRow,
    ImportPreviewRow,
    ImportReport,
    ImportResultRow,
    ImportRowError,
    MedicineWrite,
    ProductDetailOut,
    ProductImportRowModel,
    ProductUnitOut,
    ProductUnitWrite,
    ProductUpdate,
    ProductWrite,
)
from app.services.purchasing import audit
from app.services.stock import DISCRETE_UNITS

# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------


def _category_by_slug(db: Session, shop_id: UUID, slug: str) -> Category | None:
    return db.scalar(
        select(Category).where(Category.shop_id == shop_id, Category.slug == slug)
    )


def _category_by_id(db: Session, shop_id: UUID, category_id: UUID) -> Category:
    cat = db.scalar(
        select(Category).where(
            Category.id == category_id, Category.shop_id == shop_id
        )
    )
    if cat is None:
        raise NotFoundError("Category not found")
    return cat


def _assert_no_category_cycle(
    db: Session, shop_id: UUID, category_id: UUID, parent_id: UUID | None
):
    """Walk up the proposed parent chain; it must never loop back to ``category_id``."""
    seen = {category_id}
    current = parent_id
    while current is not None:
        if current in seen:
            raise ValidationError("Category hierarchy would create a cycle")
        seen.add(current)
        node = _category_by_id(db, shop_id, current)
        current = node.parent_id


def _category_out(db: Session, cat: Category) -> CategoryManageOut:
    count = db.scalar(
        select(func.count(Product.id)).where(Product.category_id == cat.id)
    ) or 0
    return CategoryManageOut(
        id=cat.id,
        name_en=cat.name_en,
        name_bn=cat.name_bn,
        slug=cat.slug,
        is_medicine=cat.is_medicine,
        loyalty_eligible=cat.loyalty_eligible,
        parent_id=cat.parent_id,
        is_active=cat.is_active,
        sort_order=cat.sort_order,
        product_count=count,
    )


def save_category(
    db: Session,
    principal: Principal,
    body: CategoryWrite,
    category_id: UUID | None = None,
) -> CategoryManageOut:
    """Create a new category or update an existing one.

    ``slug`` is the stable machine id. When updating, a slug that already
    belongs to another category is rejected; the parent chain is checked for
    cycles.
    """
    principal.require_write("catalog:write")
    try:
        if body.parent_id is not None:
            _category_by_id(db, principal.shop_id, body.parent_id)  # must exist

        existing = _category_by_slug(db, principal.shop_id, body.slug)
        if category_id is None:
            if existing is not None:
                raise ConflictError(f"Category slug '{body.slug}' already exists")
            cat = Category(shop_id=principal.shop_id, **body.model_dump())
            db.add(cat)
            db.flush()
            audit(
                db, principal, "category.create", "category", cat.id,
                **body.model_dump(mode="json"),
            )
        else:
            cat = _category_by_id(db, principal.shop_id, category_id)
            if existing is not None and existing.id != category_id:
                raise ConflictError(f"Category slug '{body.slug}' already exists")
            _assert_no_category_cycle(db, principal.shop_id, category_id, body.parent_id)
            for key, value in body.model_dump().items():
                setattr(cat, key, value)
            audit(
                db, principal, "category.update", "category", cat.id,
                **body.model_dump(mode="json"),
            )
        db.commit()
        return _category_out(db, cat)
    except Exception:
        db.rollback()
        raise


def list_managed_categories(db: Session, principal: Principal) -> list[CategoryManageOut]:
    cats = db.scalars(
        select(Category)
        .where(Category.shop_id == principal.shop_id)
        .order_by(Category.sort_order, Category.name_en)
    ).all()
    return [_category_out(db, c) for c in cats]


def set_category_active(
    db: Session, principal: Principal, category_id: UUID, active: bool
) -> CategoryManageOut:
    """Activate / deactivate a category. Deactivating hides it from pickers and
    the billing search without losing product history."""
    principal.require_write("catalog:write")
    try:
        cat = _category_by_id(db, principal.shop_id, category_id)
        cat.is_active = active
        audit(
            db, principal,
            "category.activate" if active else "category.deactivate",
            "category", cat.id, is_active=active,
        )
        db.commit()
        return _category_out(db, cat)
    except Exception:
        db.rollback()
        raise


def delete_category(db: Session, principal: Principal, category_id: UUID) -> None:
    """Hard-delete a category only when nothing references it. A category that
    still owns products or child categories must be deactivated or emptied
    first, so historical product/category links are never silently severed."""
    principal.require_write("catalog:write")
    try:
        cat = _category_by_id(db, principal.shop_id, category_id)
        products = db.scalar(
            select(func.count(Product.id)).where(Product.category_id == category_id)
        ) or 0
        if products:
            raise ValidationError(
                f"Category has {products} product(s); "
                "reassign them or deactivate the category instead"
            )
        children = db.scalar(
            select(func.count(Category.id)).where(Category.parent_id == category_id)
        ) or 0
        if children:
            raise ValidationError(
                f"Category has {children} sub-categories; move them first"
            )
        slug = cat.slug
        db.delete(cat)
        audit(db, principal, "category.delete", "category", category_id, slug=slug)
        db.commit()
    except Exception:
        db.rollback()
        raise


# ---------------------------------------------------------------------------
# Product unit validation
# ---------------------------------------------------------------------------

# Base units that are indivisible — a conversion factor on these must resolve
# to a whole number of base units (never assume e.g. a strip holds a fractional
# or fixed number of tablets).
_DISCRETE_LOWER = {u.lower() for u in DISCRETE_UNITS} | {
    "tablet",
    "capsule",
    "tab",
    "cap",
    "pcs",
}


def _validate_units(units: list[ProductUnitWrite], base_unit_name: str | None) -> None:
    """Exactly one base unit, conversion_factor == 1 on the base, discrete
    conversions must be integral (never assume e.g. strip→tablet counts —
    a configured ratio must still resolve to whole base units)."""
    names = [u.name.strip().lower() for u in units]
    if len(names) != len(set(names)):
        raise ValidationError("Unit names must be unique per product")

    base = [u for u in units if u.is_base]
    if len(base) != 1:
        raise ValidationError("Exactly one unit must be marked as the base unit")
    if base[0].conversion_factor != Decimal("1"):
        raise ValidationError("The base unit must have conversion_factor 1")

    discrete = base_unit_name and base_unit_name.lower() in _DISCRETE_LOWER
    for unit in units:
        if unit.conversion_factor <= 0:
            raise ValidationError("Unit conversion_factor must be greater than zero")
        if discrete and unit.conversion_factor != unit.conversion_factor.to_integral_value():
            raise ValidationError(
                f"Conversion factor for '{unit.name}' must be a whole number "
                "when the base unit is discrete"
            )


def _replace_units(db: Session, product: Product, units: list[ProductUnitWrite]):
    _validate_units(units, product.unit)
    # Remove existing rows then re-add — delete-orphan cascade applies on flush.
    product.units.clear()
    db.flush()
    for u in units:
        db.add(
            ProductUnit(
                product_id=product.id,
                name=u.name,
                name_bn=u.name_bn,
                conversion_factor=u.conversion_factor,
                selling_price=u.selling_price,
                is_base=u.is_base,
            )
        )
    db.flush()


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------


def _assert_unique_sku_barcode(
    db: Session,
    shop_id: UUID,
    sku: str,
    barcode: str | None,
    exclude_id: UUID | None = None,
):
    sku_q = select(Product).where(Product.shop_id == shop_id, Product.sku == sku)
    if exclude_id is not None:
        sku_q = sku_q.where(Product.id != exclude_id)
    if db.scalar(sku_q) is not None:
        raise ConflictError(f"SKU '{sku}' is already in use")

    if barcode:
        bc_q = select(Product).where(
            Product.shop_id == shop_id, Product.barcode == barcode
        )
        if exclude_id is not None:
            bc_q = bc_q.where(Product.id != exclude_id)
        if db.scalar(bc_q) is not None:
            raise ConflictError(f"Barcode '{barcode}' is already in use")


def product_by_id(db: Session, principal: Principal, product_id: UUID) -> Product:
    product = db.scalar(
        select(Product)
        .where(Product.id == product_id, Product.shop_id == principal.shop_id)
        .options(selectinload(Product.units), selectinload(Product.medicine))
    )
    if product is None:
        raise NotFoundError("Product not found")
    return product


def _has_history(db: Session, product_id: UUID) -> bool:
    """Financial or inventory history => never hard-delete."""
    checks = (
        db.scalar(
            select(func.count())
            .select_from(InvoiceItem)
            .where(InvoiceItem.product_id == product_id)
        ),
        db.scalar(
            select(func.count())
            .select_from(StockMovement)
            .where(StockMovement.product_id == product_id)
        ),
        db.scalar(
            select(func.count())
            .select_from(PurchaseItem)
            .where(PurchaseItem.product_id == product_id)
        ),
    )
    return any(c and c > 0 for c in checks)


def _product_detail(db: Session, product: Product) -> ProductDetailOut:
    base_unit = next((u for u in product.units if u.is_base), None)
    medicine = None
    if product.medicine is not None:
        m = product.medicine
        medicine = MedicineWrite(
            brand_name=m.brand_name,
            generic_name=m.generic_name,
            manufacturer=m.manufacturer,
            strength=m.strength,
            dosage_form=m.dosage_form,
            pack_size=m.pack_size,
            mrp=m.mrp,
            purchase_cost=m.purchase_cost,
            retail_price=m.retail_price,
            prescription_required=m.prescription_required,
        )
    return ProductDetailOut(
        id=product.id,
        sku=product.sku,
        barcode=product.barcode,
        name_en=product.name_en,
        name_bn=product.name_bn,
        unit=product.unit,
        is_medicine=product.is_medicine,
        is_active=product.is_active,
        stock_on_hand=product.stock_on_hand,
        low_stock_threshold=product.low_stock_threshold,
        price=base_unit.selling_price if base_unit else None,
        category_id=product.category_id,
        category_name_en=product.category.name_en if product.category else None,
        category_name_bn=product.category.name_bn if product.category else None,
        loyalty_eligible=product.loyalty_eligible,
        search_aliases=list(product.search_aliases or []),
        pack_size=product.pack_size,
        tax_rate=product.tax_rate,
        units=[ProductUnitOut.model_validate(u) for u in product.units],
        medicine=medicine,
        has_history=_has_history(db, product.id),
        created_at=product.created_at,
    )


def _upsert_medicine(product: Product, payload: MedicineWrite):
    fields = payload.model_dump()
    if product.medicine is None:
        product.medicine = MedicineDetail(product_id=product.id, source="manual", **fields)
    else:
        for key, value in fields.items():
            setattr(product.medicine, key, value)


def _insert_product(db: Session, principal: Principal, body: ProductWrite) -> Product:
    """Insert a product row + units + optional medicine detail. Flush-only —
    the caller owns the transaction boundary so a bulk import can wrap many
    inserts in one commit."""
    product = Product(
        shop_id=principal.shop_id,
        category_id=body.category_id,
        sku=body.sku,
        barcode=body.barcode,
        name_en=body.name_en,
        name_bn=body.name_bn,
        search_aliases=body.search_aliases,
        unit=body.unit,
        pack_size=body.pack_size,
        is_medicine=body.is_medicine,
        loyalty_eligible=body.loyalty_eligible,
        tax_rate=body.tax_rate,
        low_stock_threshold=body.low_stock_threshold,
        stock_on_hand=Decimal("0"),
        held_quantity=Decimal("0"),
    )
    db.add(product)
    db.flush()  # assign id before units/medicine

    for u in body.units:
        db.add(
            ProductUnit(
                product_id=product.id,
                name=u.name,
                name_bn=u.name_bn,
                conversion_factor=u.conversion_factor,
                selling_price=u.selling_price,
                is_base=u.is_base,
            )
        )
    if body.medicine is not None or body.is_medicine:
        med = body.medicine or MedicineWrite(brand_name=body.name_en, generic_name=body.name_en)
        _upsert_medicine(product, med)
    db.flush()
    db.refresh(product)
    return product


def create_product(db: Session, principal: Principal, body: ProductWrite) -> ProductDetailOut:
    """Create a product. Always starts with zero physical stock."""
    principal.require_write("catalog:write")
    try:
        _category_by_id(db, principal.shop_id, body.category_id)
        _assert_unique_sku_barcode(db, principal.shop_id, body.sku, body.barcode)
        _validate_units(body.units, body.unit)
        product = _insert_product(db, principal, body)
        audit(
            db,
            principal,
            "product.create",
            "product",
            product.id,
            sku=body.sku,
            is_medicine=body.is_medicine,
        )
        db.commit()
        return _product_detail(db, product)
    except Exception:
        db.rollback()
        raise


def update_product(
    db: Session, principal: Principal, product_id: UUID, body: ProductUpdate
) -> ProductDetailOut:
    """Edit catalogue fields. Never writes stock_on_hand / held_quantity."""
    principal.require_write("catalog:write")
    try:
        product = product_by_id(db, principal, product_id)
        if body.category_id is not None:
            _category_by_id(db, principal.shop_id, body.category_id)
        _assert_unique_sku_barcode(
            db,
            principal.shop_id,
            product.sku,
            body.barcode if body.barcode is not None else product.barcode,
            exclude_id=product.id,
        )

        for key in (
            "category_id",
            "barcode",
            "name_en",
            "name_bn",
            "search_aliases",
            "unit",
            "pack_size",
            "is_medicine",
            "loyalty_eligible",
            "tax_rate",
            "low_stock_threshold",
            "is_active",
        ):
            value = getattr(body, key)
            if value is not None:
                setattr(product, key, value)

        if body.units is not None:
            _replace_units(db, product, body.units)
        if body.medicine is not None:
            _upsert_medicine(product, body.medicine)
        elif body.is_medicine and product.medicine is None:
            _upsert_medicine(
                product,
                MedicineWrite(brand_name=product.name_en, generic_name=product.name_en),
            )

        db.flush()
        db.refresh(product)
        audit(
            db, principal, "product.update", "product", product.id,
            **body.model_dump(mode="json", exclude_unset=True),
        )
        db.commit()
        return _product_detail(db, product)
    except Exception:
        db.rollback()
        raise


def set_product_active(
    db: Session, principal: Principal, product_id: UUID, active: bool
) -> ProductDetailOut:
    """Activate or deactivate a product. Deactivation is a soft delete — the
    row and its invoice/receipt history stay intact."""
    principal.require_write("catalog:write")
    try:
        product = product_by_id(db, principal, product_id)
        product.is_active = active
        audit(
            db,
            principal,
            "product.activate" if active else "product.deactivate",
            "product",
            product.id,
            is_active=active,
        )
        db.commit()
        return _product_detail(db, product)
    except Exception:
        db.rollback()
        raise


def delete_product(db: Session, principal: Principal, product_id: UUID) -> None:
    """Hard-delete is only permitted when the product has no financial or
    inventory history; otherwise it must be deactivated instead."""
    principal.require_write("catalog:write")
    try:
        product = product_by_id(db, principal, product_id)
        if _has_history(db, product.id):
            raise ValidationError(
                "Product has sales or inventory history; deactivate it instead of deleting"
            )
        sku = product.sku
        db.delete(product)
        audit(db, principal, "product.delete", "product", product_id, sku=sku)
        db.commit()
    except Exception:
        db.rollback()
        raise


# ---------------------------------------------------------------------------
# Bulk import commit (server-side revalidation)
# ---------------------------------------------------------------------------


def _row_to_write(
    row: ImportCommitRow,
    category_id: UUID | None,
    fallback_category: UUID,
) -> ProductWrite:
    price = row.selling_price if row.selling_price is not None else Decimal("0")
    units = [
        ProductUnitWrite(
            name=row.unit,
            name_bn=row.unit,
            conversion_factor=Decimal("1"),
            selling_price=price,
            is_base=True,
        )
    ]
    med = None
    if row.is_medicine:
        med = MedicineWrite(
            brand_name=row.brand_name or row.name_en,
            generic_name=row.generic_name or row.name_en,
            manufacturer=row.manufacturer,
            strength=row.strength,
            dosage_form=row.dosage_form,
            pack_size=row.pack_size,
            mrp=row.mrp,
            purchase_cost=row.purchase_cost,
            retail_price=row.retail_price or row.selling_price,
            prescription_required=row.prescription_required,
        )
    return ProductWrite(
        category_id=category_id or fallback_category,
        sku=row.sku,
        barcode=row.barcode,
        name_en=row.name_en,
        name_bn=row.name_bn,
        search_aliases=row.search_aliases,
        unit=row.unit,
        pack_size=row.pack_size,
        is_medicine=row.is_medicine,
        units=units,
        medicine=med,
    )


def _default_category(db: Session, shop_id: UUID, is_medicine: bool) -> Category:
    slug = "medicine" if is_medicine else "grocery"
    cat = _category_by_slug(db, shop_id, slug)
    if cat is None:
        cat = db.scalar(
            select(Category)
            .where(Category.shop_id == shop_id, Category.is_medicine.is_(is_medicine))
            .order_by(Category.sort_order)
        )
    if cat is None:
        cat = Category(
            shop_id=shop_id,
            name_en="Medicine" if is_medicine else "Grocery",
            name_bn="ওষুধ" if is_medicine else "মুদি",
            slug=slug,
            is_medicine=is_medicine,
        )
        db.add(cat)
        db.flush()
    return cat


def preview_import_rows(
    db: Session, principal: Principal, parsed: list[tuple[int, dict[str, str]]]
) -> list[ImportPreviewRow]:
    """Validate each normalized row and classify it create / duplicate /
    invalid. Duplicate detection checks sku, barcode and a normalized name
    match against the live catalog."""
    principal.require("catalog:read")
    out: list[ImportPreviewRow] = []
    seen_skus: set[str] = set()
    seen_barcodes: set[str] = set()

    for row_no, mapping in parsed:
        errors: list[ImportRowError] = []
        model: ProductImportRowModel | None = None
        try:
            model = _row_from_mapping(row_no, mapping)
        except Exception as exc:
            errors.append(ImportRowError(row=row_no, message=str(exc)))

        if model is not None:
            # Within-file duplicate check
            if model.sku in seen_skus:
                errors.append(
                    ImportRowError(row=row_no, field="sku", message="Duplicate SKU in file")
                )
            seen_skus.add(model.sku)
            if model.barcode:
                if model.barcode in seen_barcodes:
                    errors.append(
                        ImportRowError(
                            row=row_no, field="barcode", message="Duplicate barcode in file"
                        )
                    )
                seen_barcodes.add(model.barcode)

        duplicate_of: str | None = None
        if model is not None and not errors:
            dup = db.scalar(
                select(Product).where(
                    Product.shop_id == principal.shop_id,
                    Product.sku == model.sku,
                )
            )
            if dup is not None:
                duplicate_of = "sku"
            elif model.barcode:
                dup_bc = db.scalar(
                    select(Product).where(
                        Product.shop_id == principal.shop_id,
                        Product.barcode == model.barcode,
                    )
                )
                if dup_bc is not None:
                    duplicate_of = "barcode"
            elif model.name_en:
                dup_name = db.scalar(
                    select(Product).where(
                        Product.shop_id == principal.shop_id,
                        func.lower(Product.name_en) == model.name_en.lower(),
                    )
                )
                if dup_name is not None:
                    duplicate_of = "name"

        if errors:
            action = "invalid"
        elif duplicate_of:
            action = "duplicate"
        else:
            action = "create"
        out.append(
            ImportPreviewRow(
                row=row_no, action=action, errors=errors, data=model, duplicate_of=duplicate_of
            )
        )
    return out


def commit_import(
    db: Session, principal: Principal, body: ImportCommit
) -> ImportReport:
    """Insert approved import rows transactionally.

    The preview is advisory — every row is re-validated against the *live*
    catalog at commit so a stale preview can't overwrite a product that was
    corrected or created after it. Rows that now collide are skipped, not
    updated; existing inventory and prices are never touched.
    """
    principal.require_write("catalog:write")
    created = skipped = errors = 0
    results: list[ImportResultRow] = []
    created_cats: list[str] = []

    for row in body.rows:
        # Each row is its own savepoint so a single bad row rolls back cleanly
        # without aborting the whole batch.
        try:
            with db.begin_nested():
                dup = db.scalar(
                    select(Product).where(
                        Product.shop_id == principal.shop_id, Product.sku == row.sku
                    )
                )
                if dup is not None:
                    skipped += 1
                    results.append(
                        ImportResultRow(
                            sku=row.sku, status="skipped_duplicate", detail="SKU exists"
                        )
                    )
                    continue
                if row.barcode:
                    dup_bc = db.scalar(
                        select(Product).where(
                            Product.shop_id == principal.shop_id,
                            Product.barcode == row.barcode,
                        )
                    )
                    if dup_bc is not None:
                        skipped += 1
                        results.append(
                            ImportResultRow(
                                sku=row.sku, status="skipped_duplicate", detail="Barcode exists"
                            )
                        )
                        continue

                category_id: UUID | None = None
                if row.category_slug:
                    cat = _category_by_slug(db, principal.shop_id, row.category_slug)
                    if cat is None:
                        if not body.create_missing_categories:
                            raise ValidationError(
                                f"Category slug '{row.category_slug}' does not exist"
                            )
                        cat = Category(
                            shop_id=principal.shop_id,
                            name_en=row.category_slug.replace("-", " ").title(),
                            name_bn=row.category_slug,
                            slug=row.category_slug,
                            is_medicine=row.is_medicine,
                        )
                        db.add(cat)
                        db.flush()
                        created_cats.append(row.category_slug)
                    category_id = cat.id

                write = _row_to_write(
                    row, category_id, _default_category(db, principal.shop_id, row.is_medicine).id
                )
                _validate_units(write.units, write.unit)
                product = _insert_product(db, principal, write)
                created += 1
                results.append(
                    ImportResultRow(sku=row.sku, status="created", product_id=product.id)
                )
        except Exception as exc:
            errors += 1
            results.append(ImportResultRow(sku=row.sku, status="error", detail=str(exc)))

    try:
        audit(
            db,
            principal,
            "product.import_commit",
            "catalog_import",
            principal.shop_id,
            created=created,
            skipped=skipped,
            errors=errors,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return ImportReport(
        created=created, skipped=skipped, errors=errors, results=results,
        categories_created=created_cats,
    )


# ---------------------------------------------------------------------------
# Import parsing (CSV + XLSX, no formula/macro execution)
# ---------------------------------------------------------------------------

_MAX_IMPORT_BYTES = 2 * 1024 * 1024  # 2 MB
_MAX_IMPORT_ROWS = 5000


class ImportParseError(Exception):
    pass


def _norm_header(h: str) -> str:
    return h.strip().lower().replace(" ", "_")


def _row_from_mapping(row_no: int, mapping: dict[str, str]) -> ProductImportRowModel:
    """Turn a raw header->value row into a validated import row, tolerant of
    missing/empty optional columns."""

    def val(*keys: str) -> str | None:
        for k in keys:
            v = mapping.get(k)
            if v is not None and str(v).strip() != "":
                return str(v).strip()
        return None

    def money(*keys: str) -> Decimal | None:
        raw = val(*keys)
        if raw is None:
            return None
        try:
            return Decimal(raw).quantize(Decimal("0.01"))
        except Exception as exc:
            raise ValidationError(f"Row {row_no}: invalid number '{raw}'") from exc

    def boolean(*keys: str) -> bool:
        raw = val(*keys)
        if raw is None:
            return False
        return raw.strip().lower() in {"1", "true", "yes", "y", "x"}

    aliases_raw = val("search_aliases", "aliases", "alias") or ""
    aliases = [a.strip() for a in aliases_raw.replace(";", ",").split(",") if a.strip()]

    return ProductImportRowModel(
        row=row_no,
        sku=val("sku", "product_sku") or "",
        name_en=val("name_en", "name", "english_name") or "",
        name_bn=val("name_bn", "bangla_name", "bn_name") or "",
        barcode=val("barcode", "ean", "code"),
        category_slug=val("category_slug", "category"),
        unit=val("unit") or "piece",
        selling_price=money("selling_price", "price", "sale_price"),
        search_aliases=aliases,
        is_medicine=boolean("is_medicine", "medicine"),
        brand_name=val("brand_name", "brand"),
        generic_name=val("generic_name", "generic"),
        manufacturer=val("manufacturer"),
        strength=val("strength"),
        dosage_form=val("dosage_form", "form"),
        pack_size=val("pack_size", "pack"),
        mrp=money("mrp"),
        purchase_cost=money("purchase_cost", "cost"),
        retail_price=money("retail_price"),
        prescription_required=boolean("prescription_required", "rx"),
    )


def _parse_csv(raw: bytes):
    import csv
    import io

    text = raw.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ImportParseError("CSV has no header row")
    headers = [_norm_header(h or "") for h in reader.fieldnames]
    rows = []
    for i, rec in enumerate(reader, start=2):
        mapped = {headers[j]: (rec.get(reader.fieldnames[j]) or "") for j in range(len(headers))}
        rows.append((i, mapped))
    return rows


def _parse_xlsx(raw: bytes):
    """Read only cached cell values from the first worksheet. openpyxl is loaded
    with ``data_only=True`` so formulas resolve to their last-computed value
    (never executed) and macros are dropped entirely."""
    import io

    from openpyxl import load_workbook
    from openpyxl.utils.exceptions import InvalidFileException

    try:
        wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    except InvalidFileException as exc:
        raise ImportParseError("Not a valid XLSX file") from exc
    except Exception as exc:
        raise ImportParseError(f"Could not read XLSX: {exc}") from exc

    ws = wb.worksheets[0]
    iterator = ws.iter_rows(values_only=True)
    try:
        header_row = next(iterator)
    except StopIteration as exc:
        raise ImportParseError("XLSX is empty") from exc
    headers = [_norm_header(str(c) if c is not None else "") for c in header_row]
    rows = []
    for i, rec in enumerate(iterator, start=2):
        mapped = {
            headers[j]: ("" if rec[j] is None else str(rec[j]))
            for j in range(min(len(headers), len(rec)))
        }
        rows.append((i, mapped))
    return rows


def parse_import_file(filename: str, raw: bytes):
    """Validate type/size/row limits, then parse to normalized rows."""
    if len(raw) == 0:
        raise ImportParseError("Uploaded file is empty")
    if len(raw) > _MAX_IMPORT_BYTES:
        raise ImportParseError("File exceeds the 2 MB limit")

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext == "csv":
        rows = _parse_csv(raw)
    elif ext in {"xlsx", "xlsm"}:
        rows = _parse_xlsx(raw)
    else:
        raise ImportParseError("Only .csv and .xlsx files are supported")

    if len(rows) > _MAX_IMPORT_ROWS:
        raise ImportParseError(f"Too many rows (limit {_MAX_IMPORT_ROWS})")
    return rows

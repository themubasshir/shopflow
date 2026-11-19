from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Date, case, cast, func, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import Principal
from app.core.errors import InsufficientStockError, NotFoundError, ValidationError
from app.models import MedicineBatch, Product, Shop, StockLot, StockMovement

ZERO = Decimal(0)
MONEY = Decimal("0.01")
QUANTITY = Decimal("0.001")
MAX_QUANTITY = Decimal("999999999.999")
MAX_MONEY = Decimal("999999999999.99")
DISCRETE_UNITS = {"piece", "pack", "strip", "box", "bottle", "sachet"}


def inventory_access(principal: Principal, *, write: bool = False) -> None:
    principal.require("reports:read")
    if write:
        principal.require_write("catalog:write")


def shop_date(db: Session, shop_id: UUID, at: datetime | None = None) -> date:
    value = at or datetime.now(UTC)
    return db.scalar(
        select(cast(func.timezone(Shop.timezone, value), Date)).where(Shop.id == shop_id)
    )


def expiry_status(batch: MedicineBatch, today: date) -> str:
    if batch.quarantined:
        return "quarantined"
    if batch.expiry_date <= today:
        return "expired"
    if not batch.is_active:
        return "inactive"
    return "depleted" if batch.quantity_on_hand <= batch.held_quantity else "available"


def eligible_batches(today: date):
    return (
        MedicineBatch.expiry_date > today,
        MedicineBatch.is_active.is_(True),
        MedicineBatch.quarantined.is_(False),
        MedicineBatch.quantity_on_hand > MedicineBatch.held_quantity,
    )


def available_stock(today: date):
    eligible = (
        select(
            func.coalesce(func.sum(MedicineBatch.quantity_on_hand - MedicineBatch.held_quantity), 0)
        )
        .where(
            MedicineBatch.product_id == Product.id,
            MedicineBatch.shop_id == Product.shop_id,
            *eligible_batches(today),
        )
        .correlate(Product)
        .scalar_subquery()
    )
    return case(
        (Product.is_medicine.is_(True), eligible),
        else_=Product.stock_on_hand - Product.held_quantity,
    )


def lock_products(db: Session, shop_id: UUID, product_ids) -> dict[UUID, Product]:
    return {
        product.id: product
        for product in db.scalars(
            select(Product)
            .options(selectinload(Product.units), selectinload(Product.category))
            .where(Product.shop_id == shop_id, Product.id.in_(product_ids))
            .order_by(Product.id)
            .with_for_update(key_share=True)
        )
    }


def find_batch(db: Session, shop_id: UUID, batch_id: UUID) -> MedicineBatch:
    batch = db.scalar(
        select(MedicineBatch)
        .where(
            MedicineBatch.id == batch_id,
            MedicineBatch.shop_id == shop_id,
        )
        .with_for_update(key_share=True)
    )
    if batch is None:
        raise NotFoundError("Medicine batch not found")
    return batch


def base_quantity(product: Product, quantity: Decimal, factor: Decimal) -> Decimal:
    base = quantity * factor
    if base > MAX_QUANTITY or base != base.quantize(QUANTITY):
        raise ValidationError("Quantity exceeds the supported base-unit precision or limit")
    if product.unit in DISCRETE_UNITS and base != base.to_integral_value():
        raise ValidationError("This product requires a whole base-unit quantity")
    return base.quantize(QUANTITY)


def plan_sale(db: Session, shop_id: UUID, lines, at: datetime):
    """Lock batch rows in ID order, then allocate eligible stock in FEFO order."""
    medicine = {p.id for p, _, _ in lines if p.is_medicine}
    if not medicine:
        return [[] for _ in lines]
    requested = defaultdict(Decimal)
    for product, quantity, _ in lines:
        requested[product.id] += quantity
    today = shop_date(db, shop_id, at)
    batches = db.scalars(
        select(MedicineBatch)
        .where(
            MedicineBatch.shop_id == shop_id,
            MedicineBatch.product_id.in_(medicine),
            *eligible_batches(today),
        )
        .order_by(MedicineBatch.product_id, MedicineBatch.id)
        .with_for_update(key_share=True)
    ).all()
    by_product = defaultdict(list)
    leftover = {}
    for batch in sorted(
        batches, key=lambda b: (b.expiry_date, b.received_at or b.created_at, b.id)
    ):
        by_product[batch.product_id].append(batch)
        leftover[batch.id] = batch.quantity_on_hand - batch.held_quantity
    for product_id in medicine:
        available = sum((leftover[b.id] for b in by_product[product_id]), ZERO)
        if available < requested[product_id]:
            raise InsufficientStockError(
                "Insufficient saleable medicine batch stock",
                details={
                    "product_id": str(product_id),
                    "available": str(available),
                    "requested": str(requested[product_id]),
                    "batch_stock": True,
                },
            )

    allocations = []
    for product, quantity, _ in lines:
        portions = []
        for batch in by_product[product.id]:
            amount = min(quantity, leftover[batch.id])
            if amount:
                portions.append((batch, amount))
                leftover[batch.id] -= amount
                quantity -= amount
            if not quantity:
                break
        allocations.append(portions)
    return allocations


def _lot_deductions(db: Session, product: Product, batch, available, amount):
    batch_id = batch.id if batch else None
    lots = db.scalars(
        select(StockLot)
        .where(
            StockLot.product_id == product.id,
            StockLot.batch_id == batch_id,
            StockLot.quantity_remaining > StockLot.held_quantity,
        )
        .order_by(StockLot.id)
        .with_for_update(key_share=True)
    ).all()
    opening = available - sum((lot.quantity_remaining - lot.held_quantity for lot in lots), ZERO)
    if opening < 0:
        raise ValidationError("Stock lots do not reconcile with physical inventory")
    from_opening = min(opening, amount)
    portions = [(None, from_opening)] if from_opening else []
    amount -= from_opening
    for lot in sorted(lots, key=lambda row: (row.created_at, row.id)):
        taken = min(amount, lot.quantity_remaining - lot.held_quantity)
        if taken:
            portions.append((lot, taken))
            amount -= taken
        if not amount:
            break
    return portions


def post_stock(
    db: Session,
    principal: Principal,
    product: Product,
    quantity: Decimal,
    *,
    movement_type: str,
    reference_type: str,
    reference_id: UUID,
    note: str | None = None,
    batch: MedicineBatch | None = None,
    lot: StockLot | None = None,
    counter_id: UUID | None = None,
    invoice_item_id: UUID | None = None,
    source_movement_id: UUID | None = None,
    held: bool = False,
) -> None:
    """Apply a movement to the locked physical projections and append ledger entries."""
    physical = batch.quantity_on_hand if batch else product.stock_on_hand
    reserved = batch.held_quantity if batch else product.held_quantity
    available = reserved if held else physical - reserved
    if (
        physical + quantity > MAX_QUANTITY
        or not 0 <= available + quantity <= MAX_QUANTITY
        or not 0 <= product.stock_on_hand + quantity <= MAX_QUANTITY
    ):
        raise InsufficientStockError("Stock movement exceeds physical inventory limits")
    if quantity > 0:
        portions = [(lot, quantity)]
    elif held or lot is not None:
        lot_available = (
            lot.held_quantity
            if held and lot
            else (lot.quantity_remaining - lot.held_quantity if lot else available)
        )
        if lot_available < -quantity:
            raise InsufficientStockError("This receipt lot has already been used")
        portions = [(lot, -quantity)]
    else:
        portions = _lot_deductions(db, product, batch, available, -quantity)

    product.stock_on_hand += quantity
    if held:
        product.held_quantity += quantity
    if batch:
        batch.quantity_on_hand += quantity
        if held:
            batch.held_quantity += quantity
    for source, portion in portions:
        if source is not None:
            if quantity < 0 or source_movement_id is not None:
                source.quantity_remaining += portion if quantity > 0 else -portion
            if held:
                source.held_quantity += portion if quantity > 0 else -portion
        db.add(
            StockMovement(
                shop_id=principal.shop_id,
                product_id=product.id,
                batch_id=batch.id if batch else None,
                stock_lot_id=source.id if source else None,
                counter_id=counter_id,
                invoice_item_id=invoice_item_id,
                source_movement_id=source_movement_id,
                held=held,
                movement_type=movement_type,
                quantity=portion if quantity > 0 else -portion,
                unit_cost=(source.cost_amount / source.quantity_received).quantize(MONEY)
                if source is not None and source.cost_amount is not None
                else None,
                reference_type=reference_type,
                reference_id=reference_id,
                note=note,
                created_by=principal.user_id,
            )
        )

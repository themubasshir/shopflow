from decimal import ROUND_DOWN, Decimal
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import Principal
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.models import (
    MedicineBatch,
    PurchaseItem,
    StockLot,
    StockMovement,
    SupplierCreditNote,
    SupplierLedger,
)
from app.schemas.returns import (
    CreditApply,
    CreditEntryOut,
    CreditNoteOut,
    CreditWrite,
    PurchaseCreditsOut,
    SupplierLotOut,
    SupplierRefundWrite,
    SupplierReturnWrite,
    SupplierShipmentOut,
)
from app.services.financial_posting import post_financial
from app.services.purchasing import audit, purchase_by_id, purchase_payable, supplier_by_id
from app.services.stock import (
    MONEY,
    ZERO,
    base_quantity,
    inventory_access,
    lock_products,
    post_stock,
)


def _lots(purchase_id):
    return (
        select(StockLot)
        .join(PurchaseItem, StockLot.purchase_item_id == PurchaseItem.id)
        .where(PurchaseItem.purchase_id == purchase_id)
    )


def _shipments(db: Session, purchase_id: UUID) -> dict[UUID, SupplierShipmentOut]:
    shipments = {}
    notes = dict(
        db.execute(
            select(SupplierCreditNote.shipment_id, SupplierCreditNote.id).where(
                SupplierCreditNote.purchase_id == purchase_id
            )
        ).all()
    )
    rows = db.execute(
        select(StockMovement.reference_id, StockLot, -func.sum(StockMovement.quantity))
        .join(StockLot, StockLot.id == StockMovement.stock_lot_id)
        .join(PurchaseItem, PurchaseItem.id == StockLot.purchase_item_id)
        .where(
            PurchaseItem.purchase_id == purchase_id,
            StockMovement.reference_type == "supplier_return",
            StockMovement.reference_id.is_not(None),
            StockMovement.quantity < 0,
        )
        .group_by(StockMovement.reference_id, StockLot.id)
        .order_by(func.min(StockMovement.created_at), StockMovement.reference_id)
    )
    for reference_id, lot, quantity in rows:
        if reference_id not in shipments:
            shipments[reference_id] = SupplierShipmentOut(
                id=reference_id,
                quantity=ZERO,
                cost=ZERO,
                credit_note_id=notes.get(reference_id),
            )
        result = shipments[reference_id]
        result.quantity += quantity
        # A shipment cap stays stable as later shipments are posted.
        result.cost += ((lot.cost_amount or ZERO) * quantity / lot.quantity_received).quantize(
            MONEY,
            rounding=ROUND_DOWN,
        )
    return shipments


def _note_out(db: Session, note: SupplierCreditNote) -> CreditNoteOut:
    rows = db.scalars(
        select(SupplierLedger)
        .where(SupplierLedger.credit_note_id == note.id)
        .order_by(SupplierLedger.created_at, SupplierLedger.id)
    ).all()
    result = CreditNoteOut.model_validate(note)
    result.applied = sum((r.amount for r in rows if r.kind == "credit_offset"), ZERO)
    result.refunded = sum((r.amount for r in rows if r.kind == "refund"), ZERO)
    result.available = -sum((r.amount for r in rows if r.kind != "credit_application"), ZERO)
    result.entries = [CreditEntryOut.model_validate(r) for r in rows]
    return result


def purchase_credits(db: Session, principal: Principal, purchase_id: UUID) -> PurchaseCreditsOut:
    inventory_access(principal)
    purchase = purchase_by_id(db, principal, purchase_id)
    items = {item.id: item for item in purchase.items}
    lots = db.scalars(_lots(purchase.id).order_by(StockLot.created_at, StockLot.id)).all()
    notes = db.scalars(
        select(SupplierCreditNote)
        .where(SupplierCreditNote.purchase_id == purchase.id)
        .order_by(SupplierCreditNote.created_at.desc())
    ).all()
    return PurchaseCreditsOut(
        payable=purchase_payable(db, purchase.id),
        lots=[
            SupplierLotOut(
                lot_id=lot.id,
                product=items[lot.purchase_item_id].product_name,
                name_bn=items[lot.purchase_item_id].product_name_bn,
                batch_number=items[lot.purchase_item_id].batch_number,
                movable=lot.quantity_remaining - lot.held_quantity,
            )
            for lot in lots
            if lot.quantity_remaining > lot.held_quantity
        ],
        shipments=list(_shipments(db, purchase.id).values()),
        notes=[_note_out(db, note) for note in notes],
    )


def send_to_supplier(
    db: Session, principal: Principal, purchase_id: UUID, body: SupplierReturnWrite, key: str
):
    inventory_access(principal, write=True)

    def send():
        purchase = purchase_by_id(db, principal, purchase_id, lock=True)
        if purchase.status not in {"received", "partially_received"}:
            raise ConflictError("Only received stock can be sent to a supplier")
        requested = {line.lot_id: line.quantity for line in body.lines}
        if len(requested) != len(body.lines):
            raise ValidationError("Select each receipt lot once")
        candidates = db.scalars(_lots(purchase.id).where(StockLot.id.in_(requested))).all()
        if len(candidates) != len(requested):
            raise NotFoundError("One or more lots do not belong to this purchase")
        products = lock_products(db, principal.shop_id, {lot.product_id for lot in candidates})
        batches = {
            b.id: b
            for b in db.scalars(
                select(MedicineBatch)
                .where(
                    MedicineBatch.id.in_({lot.batch_id for lot in candidates if lot.batch_id}),
                    MedicineBatch.shop_id == principal.shop_id,
                )
                .order_by(MedicineBatch.product_id, MedicineBatch.id)
                .with_for_update(key_share=True)
            )
        }
        lots = db.scalars(
            _lots(purchase.id)
            .where(StockLot.id.in_(requested))
            .order_by(StockLot.id)
            .with_for_update(of=StockLot, key_share=True)
            .execution_options(populate_existing=True)
        ).all()
        ref = uuid4()
        for lot in lots:
            product = products[lot.product_id]
            quantity = base_quantity(product, requested[lot.id], Decimal(1))
            post_stock(
                db,
                principal,
                product,
                -quantity,
                movement_type="return",
                reference_type="supplier_return",
                reference_id=ref,
                note=body.reason,
                batch=batches.get(lot.batch_id),
                lot=lot,
            )
        audit(
            db,
            principal,
            "purchase.supplier_return",
            "purchase",
            purchase.id,
            reference_id=str(ref),
            reason=body.reason,
        )
        db.flush()
        return _shipments(db, purchase.id)[ref]

    return post_financial(
        db, principal, key, "purchase.supplier_return", purchase_id, body, SupplierShipmentOut, send
    )


def create_credit(
    db: Session, principal: Principal, purchase_id: UUID, body: CreditWrite, key: str
):
    inventory_access(principal, write=True)

    def create():
        purchase = purchase_by_id(db, principal, purchase_id, lock=True)
        if purchase.status not in {"received", "partially_received"}:
            raise ConflictError("Credit notes require a received purchase")
        shipment = _shipments(db, purchase.id).get(body.shipment_id)
        if shipment is None or shipment.credit_note_id:
            raise ConflictError("Select a shipment that has not been credited")
        if body.amount > shipment.cost:
            raise ValidationError("Credit exceeds the recorded receipt cost of this shipment")
        note = SupplierCreditNote(
            purchase_id=purchase.id,
            supplier_id=purchase.supplier_id,
            shipment_id=shipment.id,
            reference=body.reference,
            reason=body.reason,
            amount=body.amount,
            actor_id=principal.user_id,
        )
        db.add(note)
        db.flush()
        _entry(db, principal, note, purchase.id, "credit", -body.amount)
        audit(
            db,
            principal,
            "supplier.credit_create",
            "supplier_credit_note",
            note.id,
            reference=body.reference,
            shipment_id=str(shipment.id),
            amount=str(body.amount),
            reason=body.reason,
        )
        db.flush()
        return _note_out(db, note)

    return post_financial(
        db, principal, key, "supplier.credit_create", purchase_id, body, CreditNoteOut, create
    )


def _entry(db, principal, note, purchase_id, kind, amount, *, method=None, reference=None):
    db.add(
        SupplierLedger(
            supplier_id=note.supplier_id,
            purchase_id=purchase_id,
            credit_note_id=note.id,
            kind=kind,
            amount=amount,
            method=method,
            reference=reference,
            created_by=principal.user_id,
        )
    )


def _locked_note(db, supplier_id, note_id):
    note = db.scalar(
        select(SupplierCreditNote)
        .where(SupplierCreditNote.id == note_id, SupplierCreditNote.supplier_id == supplier_id)
        .with_for_update(key_share=True)
    )
    if note is None:
        raise NotFoundError("Credit note not found")
    return note


def apply_credit(
    db: Session, principal: Principal, supplier_id: UUID, note_id: UUID, body: CreditApply, key: str
):
    inventory_access(principal, write=True)
    supplier_by_id(db, principal, supplier_id)

    def apply():
        note = _locked_note(db, supplier_id, note_id)
        purchase = purchase_by_id(db, principal, body.purchase_id, lock=True)
        if purchase.supplier_id != supplier_id:
            raise NotFoundError("Purchase does not belong to this supplier")
        if body.amount > _note_out(db, note).available or body.amount > purchase_payable(
            db, purchase.id
        ):
            raise ValidationError("Credit exceeds the available note or purchase balance")
        _entry(db, principal, note, note.purchase_id, "credit_offset", body.amount)
        _entry(db, principal, note, purchase.id, "credit_application", -body.amount)
        audit(
            db,
            principal,
            "supplier.credit_apply",
            "supplier_credit_note",
            note.id,
            purchase_id=str(purchase.id),
            amount=str(body.amount),
        )
        db.flush()
        return _note_out(db, note)

    return post_financial(
        db, principal, key, "supplier.credit_apply", note_id, body, CreditNoteOut, apply
    )


def record_supplier_refund(
    db: Session,
    principal: Principal,
    supplier_id: UUID,
    note_id: UUID,
    body: SupplierRefundWrite,
    key: str,
):
    inventory_access(principal, write=True)
    supplier_by_id(db, principal, supplier_id)

    def receive():
        note = _locked_note(db, supplier_id, note_id)
        if body.amount > _note_out(db, note).available:
            raise ValidationError("Refund exceeds the supplier receivable")
        _entry(
            db,
            principal,
            note,
            note.purchase_id,
            "refund",
            body.amount,
            method=body.method,
            reference=body.reference,
        )
        audit(
            db,
            principal,
            "supplier.refund_received",
            "supplier_credit_note",
            note.id,
            amount=str(body.amount),
            method=body.method,
            reference=body.reference,
        )
        db.flush()
        return _note_out(db, note)

    return post_financial(
        db, principal, key, "supplier.refund_received", note_id, body, CreditNoteOut, receive
    )

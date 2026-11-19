from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_authenticated_principal
from app.api.v1.purchasing import Key
from app.core.errors import PermissionDeniedError, ValidationError
from app.db.session import get_db
from app.schemas.reconciliation import FinanceReport, ReconciliationArea, ReconciliationOut
from app.schemas.returns import (
    CreditApply,
    CreditNoteOut,
    CreditWrite,
    InvoiceReturnsOut,
    PurchaseCreditsOut,
    RefundComplete,
    ResolveReturnStock,
    ReturnOut,
    ReturnWrite,
    StockResolutionOut,
    SupplierRefundWrite,
    SupplierReturnWrite,
    SupplierShipmentOut,
)
from app.services.customer_returns import (
    complete_refund,
    create_return,
    invoice_returns,
    resolve_stock,
)
from app.services.reconciliation import discrepancies, finance_report
from app.services.stock import shop_date
from app.services.supplier_credits import (
    apply_credit,
    create_credit,
    purchase_credits,
    record_supplier_refund,
    send_to_supplier,
)

router = APIRouter(tags=["returns and reconciliation"])
Caller = Annotated[Principal, Depends(get_authenticated_principal)]
Db = Annotated[Session, Depends(get_db)]


@router.get("/invoices/{invoice_id}/returns", response_model=InvoiceReturnsOut)
def history(invoice_id: UUID, db: Db, principal: Caller):
    return invoice_returns(db, principal, invoice_id)


@router.post(
    "/invoices/{invoice_id}/returns",
    response_model=ReturnOut,
    status_code=201,
    responses={200: {"model": ReturnOut}},
)
def add_return(
    invoice_id: UUID, body: ReturnWrite, db: Db, principal: Caller, key: Key, response: Response
):
    result = create_return(db, principal, invoice_id, body, key)
    if result.idempotent_replay:
        response.status_code = 200
    return result


@router.post("/invoices/{invoice_id}/returns/{return_id}/refund", response_model=ReturnOut)
def settle_refund(
    invoice_id: UUID, return_id: UUID, body: RefundComplete, db: Db, principal: Caller, key: Key
):
    return complete_refund(db, principal, invoice_id, return_id, body, key)


@router.post(
    "/invoices/{invoice_id}/return-lines/{line_id}/disposition", response_model=StockResolutionOut
)
def settle_stock(
    invoice_id: UUID, line_id: UUID, body: ResolveReturnStock, db: Db, principal: Caller, key: Key
):
    return resolve_stock(db, principal, invoice_id, line_id, body, key)


@router.get("/purchases/{purchase_id}/credits", response_model=PurchaseCreditsOut)
def credit_history(purchase_id: UUID, db: Db, principal: Caller):
    return purchase_credits(db, principal, purchase_id)


@router.post("/purchases/{purchase_id}/supplier-returns", response_model=SupplierShipmentOut)
def ship(purchase_id: UUID, body: SupplierReturnWrite, db: Db, principal: Caller, key: Key):
    return send_to_supplier(db, principal, purchase_id, body, key)


@router.post("/purchases/{purchase_id}/credits", response_model=CreditNoteOut)
def note(purchase_id: UUID, body: CreditWrite, db: Db, principal: Caller, key: Key):
    return create_credit(db, principal, purchase_id, body, key)


@router.post(
    "/suppliers/{supplier_id}/credits/{note_id}/applications", response_model=CreditNoteOut
)
def allocate(
    supplier_id: UUID, note_id: UUID, body: CreditApply, db: Db, principal: Caller, key: Key
):
    return apply_credit(db, principal, supplier_id, note_id, body, key)


@router.post("/suppliers/{supplier_id}/credits/{note_id}/refunds", response_model=CreditNoteOut)
def supplier_refund(
    supplier_id: UUID, note_id: UUID, body: SupplierRefundWrite, db: Db, principal: Caller, key: Key
):
    return record_supplier_refund(db, principal, supplier_id, note_id, body, key)


def _report_scope(principal: Principal) -> None:
    principal.require("reports:read")
    if principal.assigned_counter_ids is not None:
        raise PermissionDeniedError("Financial reports require shop-wide access")


@router.get("/reports/reconciliation", response_model=ReconciliationOut)
def reconcile(
    db: Db,
    principal: Caller,
    area: ReconciliationArea | None = None,
    entity_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    _report_scope(principal)
    return discrepancies(db, principal.shop_id, area, entity_id, limit, offset)


@router.get("/reports/financial", response_model=FinanceReport)
def financial_report(db: Db, principal: Caller, start: date | None = None, end: date | None = None):
    _report_scope(principal)
    end = end or shop_date(db, principal.shop_id)
    start = start or date.fromordinal(max(1, end.toordinal() - 29))
    if start > end or (end - start).days > 365 or end == date.max:
        raise ValidationError("Choose an inclusive date range of at most 366 days")
    return finance_report(db, principal.shop_id, start, end)

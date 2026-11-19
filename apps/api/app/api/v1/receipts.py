from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_authenticated_principal
from app.db.session import get_db
from app.schemas.receipts import InvoiceReceipt, ReceiptSettings
from app.services.receipts import (
    get_invoice_receipt,
    owner_receipt_settings,
    update_receipt_settings,
)

router = APIRouter(tags=["receipts"])
Caller = Annotated[Principal, Depends(get_authenticated_principal)]
Db = Annotated[Session, Depends(get_db)]


@router.get("/invoices/{invoice_id}/receipt", response_model=InvoiceReceipt)
def invoice_receipt(
    invoice_id: UUID, response: Response, principal: Caller, db: Db
) -> InvoiceReceipt:
    response.headers["Cache-Control"] = "private, no-store"
    return get_invoice_receipt(db, principal, invoice_id)


@router.get("/settings/receipts", response_model=ReceiptSettings)
def read_receipt_settings(response: Response, principal: Caller, db: Db) -> ReceiptSettings:
    response.headers["Cache-Control"] = "private, no-store"
    return owner_receipt_settings(db, principal)


@router.put("/settings/receipts", response_model=ReceiptSettings)
def save_receipt_settings(body: ReceiptSettings, principal: Caller, db: Db) -> ReceiptSettings:
    return update_receipt_settings(db, principal, body)

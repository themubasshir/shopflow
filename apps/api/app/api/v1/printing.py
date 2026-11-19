"""Staff-facing print management (Phase 2D-2).

Owners register printers and assign them to counters; staff enqueue prints and
inspect the queue. Agent endpoints live in ``agent.py`` — they authenticate
with a separate printer credential, never a cashier token.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_authenticated_principal
from app.core.errors import ConflictError
from app.db.session import get_db
from app.schemas.printing import (
    CounterPrinterAssign,
    PrinterCreate,
    PrinterOut,
    PrinterRegistered,
    PrinterTestPage,
    PrinterTokenRotated,
    PrinterUpdate,
    PrintJobCreate,
    PrintJobList,
    PrintJobOut,
)
from app.services import printing as svc

router = APIRouter(tags=["printing"])
Caller = Annotated[Principal, Depends(get_authenticated_principal)]
Db = Annotated[Session, Depends(get_db)]


# --- Printer management (owner) ---------------------------------------------


@router.get("/printing/printers", response_model=list[PrinterOut])
def list_printers(principal: Caller, db: Db) -> list[PrinterOut]:
    return svc.list_printers(db, principal)


@router.post("/printing/printers", response_model=PrinterRegistered, status_code=201)
def create_printer(body: PrinterCreate, principal: Caller, db: Db) -> PrinterRegistered:
    printer, token = svc.create_printer(db, principal, body)
    return PrinterRegistered(printer=printer, agent_token=token)


@router.patch("/printing/printers/{printer_id}", response_model=PrinterOut)
def update_printer(
    printer_id: uuid.UUID, body: PrinterUpdate, principal: Caller, db: Db
) -> PrinterOut:
    return svc.update_printer(db, principal, printer_id, body)


@router.post("/printing/printers/{printer_id}/rotate-token", response_model=PrinterTokenRotated)
def rotate_token(printer_id: uuid.UUID, principal: Caller, db: Db) -> PrinterTokenRotated:
    printer, token = svc.rotate_agent_token(db, principal, printer_id)
    return PrinterTokenRotated(printer=printer, agent_token=token)


@router.put("/printing/counters/{counter_id}/printer", status_code=204)
def assign_counter_printer(
    counter_id: uuid.UUID, body: CounterPrinterAssign, principal: Caller, db: Db
) -> Response:
    svc.assign_counter_printer(db, principal, counter_id, body.printer_id)
    return Response(status_code=204)


@router.post(
    "/printing/printers/{printer_id}/test-page",
    response_model=PrintJobOut,
    status_code=201,
)
def test_page(
    printer_id: uuid.UUID, principal: Caller, db: Db, body: PrinterTestPage | None = None
) -> PrintJobOut:
    """Queue a calibration/test page on one printer (owner only).

    The page proves transport, cut, alignment and Bangla shaping on real
    hardware without touching any invoice."""
    return svc.enqueue_test_page(db, principal, printer_id, body.language if body else None)


# --- Print jobs (staff) -------------------------------------------------------


@router.post("/printing/jobs", response_model=PrintJobOut, status_code=201)
def enqueue(body: PrintJobCreate, principal: Caller, db: Db) -> PrintJobOut:
    return svc.enqueue_print(db, principal, body.invoice_id, body.printer_id, body.language)


@router.post("/printing/jobs/{job_id}/reprint", response_model=PrintJobOut, status_code=201)
def reprint(job_id: uuid.UUID, principal: Caller, db: Db) -> PrintJobOut:
    """Explicit reprint: always a *new* job for the same document, linked to the
    prior one. Never mutates or reopens a completed invoice."""
    job = svc.db_get_job(db, principal, job_id)
    if job.kind == "test_page":
        return svc.enqueue_test_page(db, principal, job.printer_id, job.language)
    if job.invoice_id is None:
        raise ConflictError("Job has no document to reprint")
    return svc.enqueue_print(
        db,
        principal,
        job.invoice_id,
        job.printer_id,
        job.language,
        reprint_of_job_id=job.id,
    )


@router.get("/printing/jobs", response_model=PrintJobList)
def list_jobs(
    principal: Caller,
    db: Db,
    invoice_id: uuid.UUID | None = None,
    status_filter: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> PrintJobList:
    items, total = svc.list_jobs(db, principal, invoice_id, status_filter, limit, offset)
    return PrintJobList(items=items, total=total, limit=limit, offset=offset)


@router.get("/printing/jobs/{job_id}", response_model=PrintJobOut)
def get_job(job_id: uuid.UUID, principal: Caller, db: Db) -> PrintJobOut:
    return svc.db_get_job(db, principal, job_id)


@router.post("/printing/jobs/{job_id}/retry", response_model=PrintJobOut)
def retry(job_id: uuid.UUID, principal: Caller, db: Db) -> PrintJobOut:
    return svc.retry_job(db, principal, job_id)


@router.post("/printing/jobs/{job_id}/cancel", response_model=PrintJobOut)
def cancel(job_id: uuid.UUID, principal: Caller, db: Db) -> PrintJobOut:
    return svc.cancel_job(db, principal, job_id)

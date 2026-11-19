"""Print-agent protocol (Phase 2D-2).

The agent authenticates with its own credential — independent of any cashier
session — and is scoped to exactly one registered printer. It cannot reach
invoice data, list other printers, or fetch an arbitrary URL: the only document
it can pull is the saved-invoice PDF for a job it currently holds under lease.

Outbound flow (the agent polls the API; nothing on the LAN needs a listening
socket reachable from the internet):

    POST /print/agent/config      → transport connection detail for its printer
    POST /print/agent/claim       → lease the oldest pending job (FIFO)
    POST /print/agent/document    → single-use fetch of the saved invoice doc
    POST /print/agent/report      → printing / completed / failed
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Printer
from app.schemas.printing import (
    AgentConfig,
    AgentCredentials,
    ClaimResponse,
    DocumentRequest,
    DocumentResponse,
    JobReport,
    ReportResponse,
)
from app.schemas.receipts import InvoiceReceipt
from app.services import printing as svc

router = APIRouter(tags=["printing-agent"])
Db = Annotated[Session, Depends(get_db)]


def _agent(body: AgentCredentials, db: Session) -> Printer:
    return svc.authenticate_agent(db, body.agent_id, body.token)


@router.post("/print/agent/config", response_model=AgentConfig)
def agent_config(body: AgentCredentials, db: Db) -> AgentConfig:
    """Transport connection detail bound to this agent's printer only — an
    agent can never read another printer's host/port."""
    printer = _agent(body, db)
    return svc.agent_config(db, printer)


@router.post("/print/agent/claim", response_model=ClaimResponse)
def claim(body: AgentCredentials, db: Db) -> ClaimResponse:
    """Lease the oldest pending job for this agent's printer (FIFO).

    Returns ``job=None`` when the queue is empty. The ``claim_token`` binds the
    subsequent report to this lease; ``document_token`` authorizes one document
    fetch for this job."""
    printer = _agent(body, db)
    job, claim_token, doc_token = svc.claim_job(db, printer)
    if job is None:
        return ClaimResponse(job=None)
    return ClaimResponse(job=svc.claimed_job_view(db, job, claim_token or "", doc_token or ""))


@router.post("/print/agent/document", response_model=DocumentResponse)
def document(body: DocumentRequest, db: Db) -> DocumentResponse:
    """Exchange a job's one-time document token for a short-lived render grant.

    The agent proves its printer credential AND the per-job document secret. In
    return it receives a single-purpose ``render_url`` pointing at the web
    layer's canonical receipt-PDF route — the only document it may fetch. The
    grant authorizes exactly one invoice+language and cannot be widened."""
    printer = _agent(body, db)
    render_path, kind, invoice_id, language = svc.resolve_document(
        db, printer, body.job_id, body.document_token
    )
    return DocumentResponse(
        render_url=render_path, kind=kind, invoice_id=invoice_id, language=language
    )


class _GrantVerify(BaseModel):
    grant: str = Field(min_length=1, max_length=2000)


@router.post("/print/grants/verify")
def verify_grant(body: _GrantVerify) -> dict:
    """Introspect a render grant. Called server-to-server by the web layer to
    confirm the grant's signature and recover the scoped invoice+language. Not
    an agent endpoint — it carries no printer credential and mutates nothing."""
    return svc.verify_render_grant(body.grant)


class _GrantReceipt(BaseModel):
    grant: str = Field(min_length=1, max_length=2000)
    invoice_id: str


@router.post("/print/grants/receipt", response_model=InvoiceReceipt)
def grant_receipt(body: _GrantReceipt, db: Db) -> InvoiceReceipt:
    """Return the receipt the render grant names. The web layer calls this
    after verifying the grant so it can render the canonical PDF. The grant
    scopes both invoice and caller; an invoice id outside the grant is refused,
    as is a test-page grant (which has no invoice to render).
    """
    claims = svc.verify_render_grant(body.grant)
    if claims.get("kind") != "invoice":
        from app.core.errors import PermissionDeniedError

        raise PermissionDeniedError("Grant does not name an invoice")
    if str(claims.get("invoice_id")) != body.invoice_id:
        from app.core.errors import PermissionDeniedError

        raise PermissionDeniedError("Invoice is outside the render grant")
    import uuid

    return svc.receipt_for_grant(db, uuid.UUID(body.invoice_id))


@router.post("/print/agent/report", response_model=ReportResponse)
def report(body: JobReport, db: Db) -> ReportResponse:
    """Report physical progress for a claimed job. The ``claim_token`` proves
    the reporter holds the current lease; only that lease may transition the
    job."""
    printer = _agent(body, db)
    if body.outcome == "printing":
        svc.mark_printing(db, printer, body.job_id, body.claim_token)
    elif body.outcome == "completed":
        svc.complete_job(db, printer, body.job_id, body.claim_token)
    else:
        svc.fail_job(
            db, printer, body.job_id, body.claim_token, body.error_code, body.error_message
        )
    return ReportResponse(status="ok")

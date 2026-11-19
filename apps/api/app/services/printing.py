"""Shared thermal printing service (Phase 2D-2).

Responsibilities split across three actors:

* **Owner** registers printers, rotates agent credentials, assigns printers to
  counters and may cancel a pending job.
* **Staff** enqueue a print for a saved invoice (initial print or a reprint).
  Enqueue is read-only against the invoice — it never recreates financial
  records.
* **Agent** authenticates with its own credential (independent of any cashier
  session), atomically claims the oldest pending job for its printer under a
  lease, fetches the saved PDF through a one-time document token, then reports
  the physical outcome.

The queue is authoritative and FIFO. Claiming uses ``SELECT ... FOR UPDATE
SKIP LOCKED`` so two agents can never pull the same row. A job whose physical
outcome is unknown (lease expired, agent disconnected) is moved to
``uncertain`` and is *never* auto-reprinted; an intentional reprint creates a
new job that references the invoice and the prior job.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import Principal, assert_counter_allowed
from app.core.errors import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from app.core.security import hash_password, verify_password
from app.models import (
    AuditLog,
    Counter,
    CounterPrinter,
    Invoice,
    Printer,
    PrintJob,
)
from app.schemas.printing import (
    AgentConfig,
    ClaimedJob,
    PrinterOut,
    PrintJobOut,
)

LEASE_SECONDS = 90
# A claimed-but-not-reporting agent gets this long before the job is treated as
# uncertain. Kept comfortably longer than a single render+stream so an in-flight
# print is not prematurely reclaimed.
DOCUMENT_TTL_SECONDS = 120

_LANGUAGES: tuple[str, ...] = ("en", "bn", "bilingual")
_OPEN_STATUSES = ("claimed", "printing")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _shop_printer(db: Session, shop_id: uuid.UUID, printer_id: uuid.UUID) -> Printer:
    printer = db.get(Printer, printer_id)
    if printer is None or printer.shop_id != shop_id:
        raise NotFoundError("Printer not found")
    return printer


def _shop_counter(db: Session, shop_id: uuid.UUID, counter_id: uuid.UUID) -> Counter:
    counter = db.get(Counter, counter_id)
    if counter is None or counter.shop_id != shop_id:
        raise NotFoundError("Counter not found")
    return counter


def _printer_out(db: Session, printer: Printer) -> PrinterOut:
    counter_ids = db.scalars(
        select(CounterPrinter.counter_id).where(CounterPrinter.printer_id == printer.id)
    ).all()
    return PrinterOut(
        id=printer.id,
        name=printer.name,
        transport=printer.transport,
        agent_id=printer.agent_id,
        device_model=printer.device_model,
        paper_width_mm=printer.paper_width_mm,
        dots_width=printer.dots_width,
        dpi=printer.dpi,
        density=printer.density,
        feed_dots=printer.feed_dots,
        has_cutter=printer.has_cutter,
        is_enabled=printer.is_enabled,
        default_language=printer.default_language,
        capabilities=printer.capabilities,
        counter_ids=list(counter_ids),
    )


def _job_out(job: PrintJob) -> PrintJobOut:
    return PrintJobOut(
        id=job.id,
        kind=job.kind,
        invoice_id=job.invoice_id,
        printer_id=job.printer_id,
        counter_id=job.counter_id,
        language=job.language,
        status=job.status,
        attempts=job.attempts,
        error_code=job.error_code,
        error_message=job.error_message,
        created_at=job.created_at,
        completed_at=job.completed_at,
        reprint_of_job_id=job.reprint_of_job_id,
    )


def _audit(
    db: Session,
    principal: Principal,
    action: str,
    entity_id: uuid.UUID,
    after: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            shop_id=principal.shop_id,
            actor_user_id=principal.user_id,
            action=action,
            entity_type="print_job" if "job" in action else "printer",
            entity_id=entity_id,
            after=after or {},
        )
    )


def _new_agent_token() -> str:
    # 32 bytes → ~43 url-safe chars; high entropy, shown to the owner once.
    return secrets.token_urlsafe(32)


def _connection(transport: str, config: dict | None) -> dict:
    """Validate transport detail so an agent never receives a half-configured device.

    Only the fields the transport actually uses are stored: a stale Bluetooth
    address left over from a transport switch must not travel to the agent.
    """
    if transport == "network":
        host = str((config or {}).get("host") or "").strip()
        if not host:
            raise ValidationError(
                "A network printer needs a LAN host", details={"field": "config.host"}
            )
        raw_port = (config or {}).get("port", 9100)
        try:
            port = int(raw_port)
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                "Port must be a whole number", details={"field": "config.port"}
            ) from exc
        if not 1 <= port <= 65535:
            raise ValidationError(
                "Port must be between 1 and 65535", details={"field": "config.port"}
            )
        return {"host": host, "port": port}

    gateway = str((config or {}).get("gateway_id") or "").strip()
    if not gateway:
        raise ValidationError(
            "A Bluetooth printer needs a gateway identifier",
            details={"field": "config.gateway_id"},
        )
    address = str((config or {}).get("device_address") or "").strip() or None
    return {"gateway_id": gateway, "device_address": address}


def _capabilities(value: object) -> dict:
    """Store the capability flags, refusing a device the agent cannot drive.

    The agent only emits ESC/POS raster bitmaps (``GS v 0``). A character-only
    device would silently drop Bengali shaping, so it is rejected at the door
    instead of failing on the shop floor.
    """
    caps = value.model_dump() if hasattr(value, "model_dump") else dict(value or {})  # type: ignore[arg-type]
    if not caps.get("raster", True):
        raise ValidationError(
            "This print agent only sends ESC/POS raster bitmaps",
            details={"field": "capabilities.raster"},
        )
    return {"raster": True, "character": bool(caps.get("character", False))}


# ---------------------------------------------------------------------------
# Owner: printer management
# ---------------------------------------------------------------------------


def _require_owner(principal: Principal) -> None:
    principal.require_write("settings:write")
    if principal.role_code != "owner":
        raise PermissionDeniedError("Printer management requires shop ownership")


def list_printers(db: Session, principal: Principal) -> list[PrinterOut]:
    """Read-only printer list. Staff need it to choose where a receipt goes, so
    this one is ``sales:read`` rather than owner-only. ``PrinterOut`` never
    carries the agent token or the transport connection detail."""
    principal.require("sales:read")
    rows = db.scalars(
        select(Printer).where(Printer.shop_id == principal.shop_id).order_by(Printer.created_at)
    ).all()
    return [_printer_out(db, p) for p in rows]


def create_printer(db: Session, principal: Principal, body) -> tuple[PrinterOut, str]:
    _require_owner(principal)
    token = _new_agent_token()
    printer = Printer(
        shop_id=principal.shop_id,
        name=body.name,
        transport=body.transport,
        agent_id=body.agent_id,
        token_hash=hash_password(token),
        device_model=body.device_model,
        paper_width_mm=body.paper_width_mm,
        dots_width=body.dots_width,
        dpi=body.dpi,
        density=body.density,
        feed_dots=body.feed_dots,
        has_cutter=body.has_cutter,
        is_enabled=body.is_enabled,
        default_language=body.default_language,
        config=_connection(body.transport, body.config),
        capabilities=_capabilities(body.capabilities),
    )
    db.add(printer)
    db.flush()
    _audit(db, principal, "printer.create", printer.id, {"name": printer.name})
    db.commit()
    return _printer_out(db, printer), token


def update_printer(db: Session, principal: Principal, printer_id: uuid.UUID, body) -> PrinterOut:
    _require_owner(principal)
    printer = _shop_printer(db, principal.shop_id, printer_id)
    changes = body.model_dump(exclude_unset=True)
    if "transport" in changes or "config" in changes:
        changes["config"] = _connection(
            changes.get("transport", printer.transport),
            changes.get("config", printer.config),
        )
    if "capabilities" in changes:
        changes["capabilities"] = _capabilities(changes["capabilities"])
    for field, value in changes.items():
        setattr(printer, field, value)
    _audit(
        db,
        principal,
        "printer.update",
        printer.id,
        {k: str(v) for k, v in changes.items() if k != "config"},
    )
    db.commit()
    return _printer_out(db, printer)


def rotate_agent_token(
    db: Session, principal: Principal, printer_id: uuid.UUID
) -> tuple[PrinterOut, str]:
    """Issue a fresh agent credential, invalidating the previous one."""
    _require_owner(principal)
    printer = _shop_printer(db, principal.shop_id, printer_id)
    token = _new_agent_token()
    printer.token_hash = hash_password(token)
    _audit(db, principal, "printer.rotate_token", printer.id, {})
    db.commit()
    return _printer_out(db, printer), token


def assign_counter_printer(
    db: Session, principal: Principal, counter_id: uuid.UUID, printer_id: uuid.UUID | None
) -> None:
    """Set (or clear, ``printer_id=None``) a counter's preferred printer.

    Counters keep their identity and history; we only update the routing row.
    """
    _require_owner(principal)
    counter = _shop_counter(db, principal.shop_id, counter_id)
    existing = db.get(CounterPrinter, counter.id)
    if printer_id is None:
        if existing is not None:
            db.delete(existing)
        db.flush()
        db.commit()
        return
    printer = _shop_printer(db, principal.shop_id, printer_id)
    if existing is None:
        db.add(
            CounterPrinter(counter_id=counter.id, printer_id=printer.id, shop_id=principal.shop_id)
        )
    else:
        existing.printer_id = printer.id
    db.flush()
    db.add(
        AuditLog(
            shop_id=principal.shop_id,
            actor_user_id=principal.user_id,
            action="counter.assign_printer",
            entity_type="counter",
            entity_id=counter.id,
            after={"printer_id": str(printer.id)},
        )
    )
    db.commit()


# ---------------------------------------------------------------------------
# Staff: enqueue + inspect jobs
# ---------------------------------------------------------------------------


def _resolve_printer_for_invoice(
    db: Session, principal: Principal, invoice: Invoice, explicit: uuid.UUID | None
) -> Printer:
    """Pick the printer for a job: explicit choice, else the billing counter's
    preferred printer, else the shop's single enabled printer."""
    if explicit is not None:
        printer = _shop_printer(db, principal.shop_id, explicit)
        if not printer.is_enabled:
            raise ValidationError("Printer is disabled", details={"printer_id": str(printer.id)})
        return printer
    preferred = db.scalar(
        select(CounterPrinter.printer_id).where(CounterPrinter.counter_id == invoice.counter_id)
    )
    if preferred is not None:
        printer = _shop_printer(db, principal.shop_id, preferred)
        if printer.is_enabled:
            return printer
    enabled = db.scalars(
        select(Printer).where(Printer.shop_id == principal.shop_id, Printer.is_enabled.is_(True))
    ).all()
    if len(enabled) == 1:
        return enabled[0]
    if not enabled:
        raise ValidationError("No enabled printer is configured")
    raise ValidationError("Choose a printer", details={"code": "printer_required"})


def enqueue_print(
    db: Session,
    principal: Principal,
    invoice_id: uuid.UUID,
    printer_id: uuid.UUID | None,
    language: str | None,
    reprint_of_job_id: uuid.UUID | None = None,
) -> PrintJobOut:
    """Create a pending print job for a saved invoice.

    This is deliberately read-only against the invoice: printing can never
    recreate or mutate a completed financial record. The caller must be
    allowed to bill at the invoice's counter (same scoping as reading it).
    """
    principal.require("sales:read")
    invoice = db.get(Invoice, invoice_id)
    if invoice is None or invoice.shop_id != principal.shop_id:
        raise NotFoundError("Invoice not found")
    if invoice.status not in ("finalized", "voided", "refunded"):
        raise ValidationError("Only a finalized invoice can be printed")
    assert_counter_allowed(principal, invoice.counter_id)

    if reprint_of_job_id is not None:
        prior = db.get(PrintJob, reprint_of_job_id)
        if prior is None or prior.shop_id != principal.shop_id or prior.invoice_id != invoice.id:
            raise ValidationError("Reprint must reference a job for the same invoice")

    printer = _resolve_printer_for_invoice(db, principal, invoice, printer_id)
    lang = language if language in _LANGUAGES else printer.default_language

    job = PrintJob(
        shop_id=principal.shop_id,
        kind="invoice",
        invoice_id=invoice.id,
        printer_id=printer.id,
        requested_by=principal.user_id,
        counter_id=invoice.counter_id,
        language=lang,
        status="pending",
        reprint_of_job_id=reprint_of_job_id,
        dots_width=printer.dots_width,
        dpi=printer.dpi,
        density=printer.density,
        feed_dots=printer.feed_dots,
        meta={"invoice_number": invoice.invoice_number},
    )
    db.add(job)
    db.flush()
    db.add(
        AuditLog(
            shop_id=principal.shop_id,
            actor_user_id=principal.user_id,
            action="print_job.enqueue" if reprint_of_job_id is None else "print_job.reprint",
            entity_type="print_job",
            entity_id=job.id,
            after={
                "invoice_id": str(invoice.id),
                "printer_id": str(printer.id),
                "reprint_of": str(reprint_of_job_id) if reprint_of_job_id else None,
            },
        )
    )
    db.commit()
    return _job_out(job)


def list_jobs(
    db: Session,
    principal: Principal,
    invoice_id: uuid.UUID | None,
    status_filter: str | None,
    limit: int,
    offset: int,
) -> tuple[list[PrintJobOut], int]:
    principal.require("sales:read")
    stmt = select(PrintJob).where(PrintJob.shop_id == principal.shop_id)
    count_stmt = select(func.count(PrintJob.id)).where(PrintJob.shop_id == principal.shop_id)
    if invoice_id is not None:
        stmt = stmt.where(PrintJob.invoice_id == invoice_id)
        count_stmt = count_stmt.where(PrintJob.invoice_id == invoice_id)
    if status_filter:
        stmt = stmt.where(PrintJob.status == status_filter)
        count_stmt = count_stmt.where(PrintJob.status == status_filter)
    # Cashiers only see jobs for counters they are assigned to.
    if principal.assigned_counter_ids is not None:
        ids = list(principal.assigned_counter_ids)
        stmt = stmt.where(PrintJob.counter_id.in_(ids))
        count_stmt = count_stmt.where(PrintJob.counter_id.in_(ids))
    total = db.scalar(count_stmt) or 0
    rows = db.scalars(stmt.order_by(PrintJob.created_at.desc()).limit(limit).offset(offset)).all()
    return [_job_out(j) for j in rows], total


def db_get_job(db: Session, principal: Principal, job_id: uuid.UUID) -> PrintJobOut:
    principal.require("sales:read")
    job = db.get(PrintJob, job_id)
    if job is None or job.shop_id != principal.shop_id:
        raise NotFoundError("Print job not found")
    if job.counter_id is not None:
        assert_counter_allowed(principal, job.counter_id)
    return _job_out(job)


def retry_job(db: Session, principal: Principal, job_id: uuid.UUID) -> PrintJobOut:
    """Requeue a ``failed`` job. ``uncertain`` jobs are never auto-retried —
    they require an explicit reprint so a possibly-printed receipt is not
    silently duplicated."""
    principal.require("sales:write")
    job = db.get(PrintJob, job_id)
    if job is None or job.shop_id != principal.shop_id:
        raise NotFoundError("Print job not found")
    if job.counter_id is not None:
        assert_counter_allowed(principal, job.counter_id)
    if job.status == "uncertain":
        raise ConflictError(
            "Job outcome is uncertain; reprint explicitly instead of retrying",
            details={"code": "uncertain_requires_reprint"},
        )
    if job.status not in ("failed", "cancelled"):
        raise ConflictError("Only a failed or cancelled job can be retried")
    job.status = "pending"
    job.claim_token = None
    job.lease_until = None
    job.claimed_by_agent = None
    job.completed_at = None
    db.add(
        AuditLog(
            shop_id=principal.shop_id,
            actor_user_id=principal.user_id,
            action="print_job.retry",
            entity_type="print_job",
            entity_id=job.id,
        )
    )
    db.commit()
    return _job_out(job)


def cancel_job(db: Session, principal: Principal, job_id: uuid.UUID) -> PrintJobOut:
    principal.require("sales:write")
    job = db.get(PrintJob, job_id)
    if job is None or job.shop_id != principal.shop_id:
        raise NotFoundError("Print job not found")
    if job.counter_id is not None:
        assert_counter_allowed(principal, job.counter_id)
    if job.status not in ("pending", "failed", "uncertain"):
        raise ConflictError("Only a queued or failed job can be cancelled")
    job.status = "cancelled"
    job.completed_at = datetime.now(UTC)
    db.add(
        AuditLog(
            shop_id=principal.shop_id,
            actor_user_id=principal.user_id,
            action="print_job.cancel",
            entity_type="print_job",
            entity_id=job.id,
        )
    )
    db.commit()
    return _job_out(job)


# ---------------------------------------------------------------------------
# Agent: authenticate, claim, report
# ---------------------------------------------------------------------------


def authenticate_agent(db: Session, agent_id: str, token: str) -> Printer:
    """Resolve an agent to its printer. Independent of cashier sessions.

    ``verify_password`` always runs a hash check so an unknown agent costs the
    same as a wrong token (no enumeration by timing).
    """
    printer = db.scalar(select(Printer).where(Printer.agent_id == agent_id))
    if printer is None or not verify_password(token, printer.token_hash if printer else None):
        raise AuthenticationError("Invalid agent credentials")
    if not printer.is_enabled:
        raise AuthenticationError("Printer is disabled")
    return printer


def agent_config(db: Session, printer: Printer) -> AgentConfig:
    """Return only the transport connection detail the bound agent needs."""
    return AgentConfig(
        printer_id=printer.id,
        agent_id=printer.agent_id,
        transport=printer.transport,
        config=printer.config,
    )


def _expire_leases(db: Session, printer: Printer) -> None:
    """Reap leases that ran out without a report. A job that reached
    ``printing`` may physically have printed, so it goes to ``uncertain``
    (never auto-requeue). A job still in ``claimed`` — the agent likely died
    before fetching — is returned to ``pending`` for a safe retry."""
    now = datetime.now(UTC)
    stuck = db.scalars(
        select(PrintJob)
        .where(
            PrintJob.printer_id == printer.id,
            PrintJob.status.in_(_OPEN_STATUSES),
            PrintJob.lease_until < now,
        )
        .with_for_update(skip_locked=True)
    ).all()
    for job in stuck:
        if job.status == "printing":
            job.status = "uncertain"
            job.error_code = "lease_expired"
            job.error_message = "Agent stopped reporting while printing"
        else:
            job.status = "pending"
            job.error_code = None
            job.error_message = None
        job.claim_token = None
        job.lease_until = None
        job.claimed_by_agent = None
    if stuck:
        # Commit the reaped state before the claim SELECT: the rows we just
        # updated are still write-locked in this transaction, and a
        # ``FOR UPDATE SKIP LOCKED`` in the same transaction would skip them.
        # Reaping is independent housekeeping, so committing it separately keeps
        # the subsequent claim atomic.
        db.commit()


def claim_job(db: Session, printer: Printer) -> tuple[PrintJob | None, str | None, str | None]:
    """Atomically lease the oldest pending job to this agent's printer.

    Returns ``(job, claim_token, document_token)``. Both secrets are generated
    here and only their argon2 hashes are stored, so a report is bound to the
    live lease and the saved document can be fetched exactly once.
    ``SKIP LOCKED`` makes concurrent claims pick distinct rows.
    """
    _expire_leases(db, printer)
    job = db.scalar(
        select(PrintJob)
        .where(PrintJob.printer_id == printer.id, PrintJob.status == "pending")
        .order_by(PrintJob.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if job is None:
        db.commit()
        return None, None, None

    claim_token = secrets.token_urlsafe(24)
    doc_secret = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    job.status = "claimed"
    job.attempts += 1
    job.claim_token = claim_token
    job.claimed_by_agent = printer.agent_id
    job.lease_until = now + timedelta(seconds=LEASE_SECONDS)
    job.document_token_hash = hash_password(doc_secret)
    job.document_issued_at = now
    job.error_code = None
    job.error_message = None
    db.commit()
    return job, claim_token, doc_secret


def claimed_job_view(
    db: Session, job: PrintJob, claim_token: str, document_token: str
) -> ClaimedJob:
    invoice = db.get(Invoice, job.invoice_id) if job.invoice_id else None
    printer = db.get(Printer, job.printer_id)
    return ClaimedJob(
        id=job.id,
        kind=job.kind,
        invoice_id=job.invoice_id,
        invoice_number=invoice.invoice_number if invoice else None,
        language=job.language,
        claim_token=claim_token,
        document_token=document_token,
        lease_seconds=LEASE_SECONDS,
        dots_width=job.dots_width,
        dpi=job.dpi,
        density=job.density,
        feed_dots=job.feed_dots,
        paper_width_mm=printer.paper_width_mm if printer else 80,
        has_cutter=printer.has_cutter if printer else False,
    )


def _job_for_claim(db: Session, printer: Printer, job_id: uuid.UUID, claim_token: str) -> PrintJob:
    job = db.get(PrintJob, job_id)
    if job is None or job.printer_id != printer.id:
        raise NotFoundError("Print job not found")
    # Only the holder of the current lease may report. A stale claim_token (from
    # an expired/reclaimed lease) is rejected so an old agent cannot corrupt a
    # job another agent now owns.
    if not job.claim_token or job.claim_token != claim_token:
        raise ConflictError("Job is not leased to this claim", details={"code": "stale_claim"})
    return job


def mark_printing(db: Session, printer: Printer, job_id: uuid.UUID, claim_token: str) -> None:
    job = _job_for_claim(db, printer, job_id, claim_token)
    if job.status != "claimed":
        raise ConflictError("Job is not in a claimable state")
    job.status = "printing"
    # Streaming can take longer than claim setup for very long receipts; extend
    # the lease so a legitimate long print is not reaped mid-way.
    job.lease_until = datetime.now(UTC) + timedelta(seconds=LEASE_SECONDS)
    db.commit()


def complete_job(db: Session, printer: Printer, job_id: uuid.UUID, claim_token: str) -> None:
    job = _job_for_claim(db, printer, job_id, claim_token)
    if job.status not in _OPEN_STATUSES:
        raise ConflictError("Job is not in progress")
    job.status = "completed"
    job.completed_at = datetime.now(UTC)
    job.lease_until = None
    db.commit()


def fail_job(
    db: Session,
    printer: Printer,
    job_id: uuid.UUID,
    claim_token: str,
    error_code: str | None,
    error_message: str | None,
) -> None:
    job = _job_for_claim(db, printer, job_id, claim_token)
    if job.status not in _OPEN_STATUSES:
        raise ConflictError("Job is not in progress")
    job.status = "failed"
    # Sanitized, bounded error; never include customer financial detail.
    job.error_code = (error_code or "print_failed")[:60]
    job.error_message = (error_message or "")[:400] or None
    job.lease_until = None
    job.claim_token = None
    job.claimed_by_agent = None
    db.commit()


# ---------------------------------------------------------------------------
# Document fetch (one-time token)
# ---------------------------------------------------------------------------


def enqueue_test_page(
    db: Session, principal: Principal, printer_id: uuid.UUID, language: str | None
) -> PrintJobOut:
    """Queue a printer calibration/test page for one printer.

    A test page is a first-class job (``kind="test_page"``) so it flows through
    the same queue, agent, raster and cut path as a receipt — but it is not tied
    to any invoice and never touches financial data.
    """
    _require_owner(principal)
    printer = _shop_printer(db, principal.shop_id, printer_id)
    lang = language if language in _LANGUAGES else printer.default_language
    job = PrintJob(
        shop_id=principal.shop_id,
        kind="test_page",
        invoice_id=None,
        printer_id=printer.id,
        requested_by=principal.user_id,
        counter_id=None,
        language=lang,
        status="pending",
        dots_width=printer.dots_width,
        dpi=printer.dpi,
        density=printer.density,
        feed_dots=printer.feed_dots,
        meta={"printer_name": printer.name},
    )
    db.add(job)
    db.flush()
    db.add(
        AuditLog(
            shop_id=principal.shop_id,
            actor_user_id=principal.user_id,
            action="print_job.test_page",
            entity_type="print_job",
            entity_id=job.id,
            after={"printer_id": str(printer.id)},
        )
    )
    db.commit()
    return _job_out(job)


def resolve_document(
    db: Session, printer: Printer, job_id: uuid.UUID, key: str
) -> tuple[str, str, uuid.UUID | None, str]:
    """Validate a single-use document token and mint a render grant.

    The agent must own the job's printer and hold the live lease's document
    secret. On success the secret is burned and a short-lived render grant is
    returned — the agent presents it to the canonical web render route, which is
    the ONLY document it may fetch. Returns
    ``(render_path, kind, invoice_id, language)``.
    """
    from app.core.security import create_render_grant

    job = db.get(PrintJob, job_id)
    if job is None or job.document_token_hash is None:
        raise AuthenticationError("Invalid document token")
    if job.printer_id != printer.id:
        raise PermissionDeniedError("Job does not belong to this printer")
    if job.status not in _OPEN_STATUSES:
        raise ConflictError("Job is not active")
    issued = job.document_issued_at
    if issued is None or (datetime.now(UTC) - issued) > timedelta(seconds=DOCUMENT_TTL_SECONDS):
        raise AuthenticationError("Document token expired")
    if not verify_password(key, job.document_token_hash):
        raise AuthenticationError("Invalid document token")

    invoice_id: uuid.UUID | None = None
    if job.kind == "invoice":
        invoice = db.get(Invoice, job.invoice_id) if job.invoice_id else None
        if invoice is None:
            raise NotFoundError("Invoice not found")
        invoice_id = invoice.id
    elif job.kind != "test_page":
        raise ValidationError("Unsupported print job kind")

    # Burn the token: one claim, one document fetch.
    job.document_token_hash = None
    db.commit()

    grant = create_render_grant(
        kind=job.kind,
        language=job.language,
        job_id=str(job.id),
        invoice_id=str(invoice_id) if invoice_id else None,
        printer_name=printer.name,
        paper_width_mm=printer.paper_width_mm,
        dots_width=job.dots_width,
    )
    render_path = f"/api/print/render?grant={grant}"
    return render_path, job.kind, invoice_id, job.language


def verify_render_grant(token: str) -> dict:
    """Introspect a render grant for the web layer. Returns the scoped claims
    (``invoice_id``, ``language``, ``job_id``) so the web route can render
    exactly the named document. The grant is single-purpose; verifying it does
    not consume it (the web render is itself idempotent/read-only)."""
    from app.core.security import decode_render_grant

    return decode_render_grant(token)


def receipt_for_grant(db: Session, invoice_id: uuid.UUID) -> object:
    """Resolve the invoice the grant names into a receipt via the canonical
    snapshot service. The grant is the authorization — the caller (web layer)
    is trusted to render only the invoice+language the grant scopes. The
    synthetic principal is read-scoped so this never mutates."""
    from app.services.receipts import get_invoice_receipt

    principal = Principal(
        user_id=uuid.uuid4(),
        shop_id=_invoice_shop(db, invoice_id),
        email="",
        name="print-agent",
        role_code="agent",
        permissions=frozenset({"sales:read"}),
        assigned_counter_ids=None,
    )
    return get_invoice_receipt(db, principal, invoice_id)


def _invoice_shop(db: Session, invoice_id: uuid.UUID) -> uuid.UUID:
    shop_id = db.scalar(select(Invoice.shop_id).where(Invoice.id == invoice_id))
    if shop_id is None:
        raise NotFoundError("Invoice not found")
    return shop_id

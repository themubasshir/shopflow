"""Schemas for the shared thermal-printing domain (Phase 2D-2)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import ORMModel

ReceiptLanguage = Literal["en", "bn", "bilingual"]
PrinterTransport = Literal["network", "bluetooth"]
PrintJobStatus = Literal[
    "pending", "claimed", "printing", "completed", "failed", "uncertain", "cancelled"
]


# --- Printer management ------------------------------------------------------


class PrinterCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120)
    transport: PrinterTransport = "network"
    agent_id: str = Field(min_length=1, max_length=80)
    paper_width_mm: int = Field(default=80, gt=0, le=210)
    dots_width: int = Field(default=576, gt=0, le=2048)
    dpi: int = Field(default=203, gt=0, le=1200)
    has_cutter: bool = True
    is_enabled: bool = True
    default_language: ReceiptLanguage = "bilingual"
    # Transport-specific connection detail only the bound agent may read.
    config: dict | None = None


class PrinterUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=120)
    transport: PrinterTransport | None = None
    agent_id: str | None = Field(default=None, min_length=1, max_length=80)
    paper_width_mm: int | None = Field(default=None, gt=0, le=210)
    dots_width: int | None = Field(default=None, gt=0, le=2048)
    dpi: int | None = Field(default=None, gt=0, le=1200)
    has_cutter: bool | None = None
    is_enabled: bool | None = None
    default_language: ReceiptLanguage | None = None
    config: dict | None = None


class PrinterOut(ORMModel):
    id: UUID
    name: str
    transport: str
    agent_id: str
    paper_width_mm: int
    dots_width: int
    dpi: int
    has_cutter: bool
    is_enabled: bool
    default_language: str
    # config and token are write-only to owners; never echoed back.
    counter_ids: list[UUID] = []


class PrinterRegistered(ORMModel):
    """Returned exactly once on create/rotate: the only place the raw agent
    token is ever revealed. Store it in the agent's config."""

    printer: PrinterOut
    agent_token: str


class PrinterTokenRotated(ORMModel):
    printer: PrinterOut
    agent_token: str


class CounterPrinterAssign(BaseModel):
    printer_id: UUID | None = None


# --- Staff-facing print jobs -------------------------------------------------


class PrintJobCreate(BaseModel):
    invoice_id: UUID
    printer_id: UUID | None = None
    language: ReceiptLanguage | None = None


class PrinterTestPage(BaseModel):
    language: ReceiptLanguage | None = None


class PrintJobOut(ORMModel):
    id: UUID
    kind: str
    invoice_id: UUID | None
    printer_id: UUID
    counter_id: UUID | None
    language: str
    status: str
    attempts: int
    error_code: str | None
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None
    reprint_of_job_id: UUID | None


# --- Agent protocol ----------------------------------------------------------


class AgentCredentials(BaseModel):
    agent_id: str = Field(min_length=1, max_length=80)
    token: str = Field(min_length=8, max_length=200)


class ClaimedJob(ORMModel):
    """What an agent needs to render one job. The document is fetched once via
    ``document_token``; the calibration snapshot is authoritative for raster."""

    id: UUID
    kind: str
    invoice_id: UUID | None
    invoice_number: str | None
    language: str
    claim_token: str
    document_token: str
    lease_seconds: int
    dots_width: int
    dpi: int
    paper_width_mm: int
    has_cutter: bool


class ClaimResponse(ORMModel):
    job: ClaimedJob | None = None


class DocumentRequest(AgentCredentials):
    job_id: UUID
    document_token: str = Field(min_length=1, max_length=200)


class DocumentResponse(ORMModel):
    """A short-lived, single-purpose render grant. The agent presents
    ``render_url`` to the web layer's canonical receipt-PDF route; the grant
    authorizes exactly one invoice+language render and cannot be widened."""

    render_url: str
    kind: str
    invoice_id: UUID | None
    language: str


class JobReport(AgentCredentials):
    job_id: UUID
    claim_token: str = Field(min_length=1, max_length=64)
    outcome: Literal["printing", "completed", "failed"]
    error_code: str | None = Field(default=None, max_length=60)
    error_message: str | None = Field(default=None, max_length=400)


class ReportResponse(ORMModel):
    status: str


# --- Agent config (transport detail the bound agent may read) ---------------


class AgentConfig(ORMModel):
    printer_id: UUID
    agent_id: str
    transport: str
    config: dict | None


# --- Staff job listing ------------------------------------------------------


class PrintJobList(ORMModel):
    items: list[PrintJobOut]
    total: int
    limit: int
    offset: int

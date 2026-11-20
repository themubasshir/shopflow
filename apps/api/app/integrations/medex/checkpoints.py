"""Checkpoint / resume for a MedEx import run.

A run's progress lives on the ``medicine_catalog_import_runs`` row itself:
``last_index_page`` (how far index discovery got), ``pending_urls`` (the
detail pages still to fetch) and the discovered/fetched/staged/failed
counters. Persisting after each unit of work means an interrupted run can be
resumed exactly where it stopped — index pages are not re-fetched and detail
URLs already staged are not re-requested.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import MedicineCatalogImportRun


def mark_running(db: Session, run: MedicineCatalogImportRun) -> None:
    run.status = "running"
    from datetime import UTC, datetime

    if run.started_at is None:
        run.started_at = datetime.now(UTC)
    db.flush()


def save_index_progress(
    db: Session,
    run: MedicineCatalogImportRun,
    *,
    page: int,
    new_urls: list[str],
    last_page_seen: int | None,
) -> None:
    """Record that index ``page`` was parsed and its detail URLs queued."""
    run.last_index_page = page
    if last_page_seen:
        run.last_page_seen = last_page_seen
    pending = list(run.pending_urls or [])
    seen = set(pending)
    for u in new_urls:
        if u not in seen:
            pending.append(u)
            seen.add(u)
    run.pending_urls = pending
    run.discovered = len(pending) + run.fetched  # queued + already done
    db.flush()


def pop_next_url(run: MedicineCatalogImportRun) -> str | None:
    pending = list(run.pending_urls or [])
    return pending[0] if pending else None


def record_detail_done(
    db: Session, run: MedicineCatalogImportRun, url: str, *, staged: bool
) -> None:
    pending = [u for u in (run.pending_urls or []) if u != url]
    run.pending_urls = pending
    run.fetched += 1
    if staged:
        run.staged += 1
    db.flush()


def record_detail_error(db: Session, run: MedicineCatalogImportRun, url: str, error: str) -> None:
    """Push a failed detail URL to the retry queue (end of pending) + error list."""
    pending = [u for u in (run.pending_urls or []) if u != url]
    pending.append(url)  # re-queue at the end — failed-record retry queue
    run.pending_urls = pending
    run.fetched += 1
    run.failed += 1
    errors = list(run.errors or [])
    errors.append({"url": url, "error": error[:500]})
    run.errors = errors[-500:]
    db.flush()


def finish(db: Session, run: MedicineCatalogImportRun, status: str) -> None:
    from datetime import UTC, datetime

    run.status = status
    run.finished_at = datetime.now(UTC)
    db.flush()

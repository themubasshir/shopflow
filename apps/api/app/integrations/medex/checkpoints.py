"""Checkpoint / resume for a MedEx import run.

A run's progress lives on the ``medicine_catalog_import_runs`` row itself:
``last_index_page`` (how far index discovery got), ``pending_urls`` (the
detail pages still to fetch) and the discovered/fetched/staged/failed
counters. Persisting after each unit of work means an interrupted run can be
resumed exactly where it stopped — index pages are not re-fetched and detail
URLs already staged are not re-requested.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MedicineCatalogImportRun, MedicineCatalogManifest

# After this many fetch attempts a detail URL is marked failed rather than
# re-queued — bounds retrying a persistently-failing page so a full run can
# always terminate. Index-page fetch errors abort discovery (see importer).
MAX_DETAIL_ATTEMPTS = 3


def upsert_manifest(
    db: Session,
    run: MedicineCatalogImportRun,
    *,
    source_id,
    external_id: str,
    url: str,
    brand_label: str | None,
    index_page: int,
) -> None:
    """Record a discovered detail URL in the deduplicated manifest.

    Keyed on ``(source, external_id)`` — re-discovery updates provenance in
    place instead of duplicating. New rows start ``pending`` with 0 attempts.
    """
    existing = db.scalar(
        select(MedicineCatalogManifest).where(
            MedicineCatalogManifest.source_id == source_id,
            MedicineCatalogManifest.external_id == external_id,
        )
    )
    if existing is None:
        db.add(
            MedicineCatalogManifest(
                source_id=source_id,
                run_id=run.id,
                external_id=external_id,
                url=url,
                brand_label=brand_label,
                index_page=index_page,
                discovered_at=datetime.now(UTC),
                attempts=0,
                state="pending",
            )
        )
    else:
        existing.url = url
        if brand_label:
            existing.brand_label = brand_label
        existing.index_page = index_page
        if existing.run_id is None:
            existing.run_id = run.id
    db.flush()


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


def _manifest_for_url(db: Session, run: MedicineCatalogImportRun, url: str):
    """Find the manifest row matching a pending URL (by source + external_id)."""
    from app.integrations.medex.index_parser import detail_id_from_url

    ext = detail_id_from_url(url)
    if not ext:
        return None
    return db.scalar(
        select(MedicineCatalogManifest).where(
            MedicineCatalogManifest.source_id == run.source_id,
            MedicineCatalogManifest.external_id == ext,
        )
    )


def record_detail_done(
    db: Session, run: MedicineCatalogImportRun, url: str, *, staged: bool
) -> None:
    pending = [u for u in (run.pending_urls or []) if u != url]
    run.pending_urls = pending
    run.fetched += 1
    if staged:
        run.staged += 1
    m = _manifest_for_url(db, run, url)
    if m is not None:
        m.state = "staged" if staged else m.state
    db.flush()


def record_detail_error(db: Session, run: MedicineCatalogImportRun, url: str, error: str) -> None:
    """Record a failed detail fetch.

    The URL is re-queued at the end of ``pending`` for a bounded retry; once its
    manifest ``attempts`` reaches ``MAX_DETAIL_ATTEMPTS`` it is dropped from the
    queue and the manifest row is marked ``failed`` so the run can terminate.
    """
    pending = [u for u in (run.pending_urls or []) if u != url]
    run.fetched += 1
    run.failed += 1

    m = _manifest_for_url(db, run, url)
    if m is not None:
        m.attempts += 1
        if m.attempts >= MAX_DETAIL_ATTEMPTS:
            m.state = "failed"
            # do NOT re-queue — retry budget exhausted
        else:
            pending.append(url)  # re-queue at the end for another attempt
    else:
        pending.append(url)  # no manifest row (legacy) -> single re-queue
    run.pending_urls = pending

    errors = list(run.errors or [])
    errors.append({"url": url, "error": error[:500], "attempt": m.attempts if m else 1})
    run.errors = errors[-500:]
    db.flush()


def finish(db: Session, run: MedicineCatalogImportRun, status: str) -> None:
    from datetime import UTC, datetime

    run.status = status
    run.finished_at = datetime.now(UTC)
    db.flush()

"""The MedEx collector orchestrator.

Drives index-page discovery + detail-page fetching inside the authorized
limits, staging every parsed medicine. Everything is checkpointed so an
interrupted run resumes cleanly. ``stop_check`` lets the caller abort the run
gracefully (e.g. a cooperative cancel or a test that wants to interrupt).

The collector fetches each detail page's English variant and its ``/bn``
variant (to capture Bangla names) — two requests per medicine, paced by the
client's ``min_interval``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol

from sqlalchemy.orm import Session

from app.integrations.medex import checkpoints as ck
from app.integrations.medex.client import FetchError, MedexClient
from app.integrations.medex.detail_parser import parse_detail
from app.integrations.medex.index_parser import parse_index
from app.integrations.medex.repository import get_or_create_source, stage_detail
from app.integrations.medex.schemas import MedicineDetail
from app.models import MedicineCatalogImportRun

logger = logging.getLogger("shopflow.medex")


class IndexFetcher(Protocol):
    """Supplies index-page HTML. Lets tests inject fixtures instead of HTTP."""

    def fetch_index(self, page: int) -> tuple[str, str]: ...  # (html, url)

    def fetch_detail(self, url: str) -> tuple[str, bytes]: ...  # (html, bytes)


class LiveFetcher:
    """Real HTTP fetcher (throttled client). English + Bangla variants."""

    def __init__(self, client: MedexClient, base: str = "https://medex.com.bd"):
        self.client = client
        self.base = base

    def fetch_index(self, page: int) -> tuple[str, str]:
        url = f"{self.base}/brands" if page <= 1 else f"{self.base}/brands?page={page}"
        res = self.client.get(url)
        return res.text, url

    def fetch_detail(self, url: str) -> tuple[str, bytes]:
        res = self.client.get(url)
        return res.text, res.content


def _merge_bn(detail: MedicineDetail, bn: MedicineDetail | None) -> None:
    if bn is None:
        return
    detail.brand_name_bn = detail.brand_name_bn or bn.brand_name_bn
    detail.generic_name_bn = detail.generic_name_bn or bn.generic_name_bn
    detail.manufacturer_bn = detail.manufacturer_bn or bn.manufacturer_bn
    detail.strength_bn = detail.strength_bn or bn.strength_bn
    detail.dosage_form_bn = detail.dosage_form_bn or bn.dosage_form_bn
    # Bangla page is authoritative for *_bn only; never let it clobber EN fields.


def _looks_like_gate(html: str, url: str) -> bool:
    """True when MedEx served its security-check instead of a medicine page.

    The site's anti-bot layer answers detail URLs with HTTP 200 + a
    ``/captcha-challenge`` page. Per the spec we never *bypass* a challenge —
    we detect it and stop, rather than stage thousands of invalid rows. The
    markers are deliberately specific so a real medicine page (which mentions
    none of them in the <title>) never trips the detector.
    """
    if "/captcha-challenge" in url:
        return True
    head = html[:4000].lower()
    return (
        "security check" in head
        or "captcha-challenge" in head
        or ("captcha" in head and "challenge" in head and "brand" not in head)
    )


def run_import(
    db: Session,
    fetcher: IndexFetcher,
    run: MedicineCatalogImportRun,
    *,
    fetch_bn: bool = False,
    detail_fetcher=None,
    stop_check: Callable[[], bool] = lambda: False,
    auto_promote: bool = False,
    principal=None,
) -> MedicineCatalogImportRun:
    """Execute one import run end-to-end, committing checkpoints along the way.

    ``detail_fetcher`` optionally supplies a second callable for Bangla pages
    (defaults to the same fetcher). ``stop_check`` is polled each iteration;
    returning True marks the run ``interrupted`` and returns — resumable later.

    ``auto_promote`` + ``principal`` (Phase 3C): when set, each staged medicine
    is immediately promoted to a zero-stock, unpriced product via the bulk
    promoter — no manual approval needed. Already-imported/ambiguous/invalid
    rows are skipped or held in review by the same classification rules.
    """
    source = get_or_create_source(db)
    ck.mark_running(db, run)
    db.commit()

    # ---- Phase 1: index discovery -----------------------------------------
    page = run.last_index_page + 1 if run.last_index_page else (run.index_start or 1)
    last_seen = run.last_page_seen
    while True:
        if run.index_limit is not None and page > (run.index_start + run.index_limit - 1):
            break
        if last_seen is not None and page > last_seen:
            break
        if stop_check():
            ck.finish(db, run, "interrupted")
            db.commit()
            return run
        try:
            html, url = fetcher.fetch_index(page)
        except FetchError as exc:
            ck.record_detail_error(db, run, f"index:{page}", exc.detail)
            db.commit()
            break
        parsed = parse_index(html, url)
        last_seen = parsed.last_page or last_seen
        # Persist the deduplicated manifest (one row per external_id) so each
        # discovered medicine keeps index-page provenance + a retry budget.
        for card in parsed.cards:
            ck.upsert_manifest(
                db,
                run,
                source_id=source.id,
                external_id=card.source_id,
                url=card.url,
                brand_label=card.brand_name,
                index_page=page,
            )
        ck.save_index_progress(
            db, run, page=page, new_urls=[c.url for c in parsed.cards], last_page_seen=last_seen
        )
        db.commit()
        logger.info("medex index page=%d cards=%d last=%s", page, len(parsed.cards), last_seen)
        if not parsed.cards:  # empty page -> end of catalogue
            break
        page += 1
        # When the caller set an explicit index range, keep scanning it so the
        # manifest reflects every requested page. When they didn't, a capped
        # detail pilot only needs enough URLs queued to satisfy detail_limit —
        # stop early instead of crawling the whole index for a 12-detail run.
        if (
            run.index_limit is None
            and run.detail_limit is not None
            and len(run.pending_urls or []) >= run.detail_limit
        ):
            break

    # ---- Phase 2: detail fetch + stage -------------------------------------
    detail_fetcher = detail_fetcher or fetcher
    while True:
        if run.detail_limit is not None and run.staged + run.failed >= run.detail_limit:
            break
        url = ck.pop_next_url(run)
        if url is None:
            break
        if stop_check():
            ck.finish(db, run, "interrupted")
            db.commit()
            return run
        try:
            html, content = detail_fetcher.fetch_detail(url)
            if _looks_like_gate(html, url):
                # Security gate: stop cleanly, leave the URL pending so it can
                # be re-fetched after the challenge clears. Do NOT stage the
                # challenge page as a medicine and never try to bypass it.
                logger.warning("medex security gate at %s — stopping run", url)
                ck.push_back_url(db, run, url)
                ck.finish(db, run, "gated")
                db.commit()
                return run
            detail = parse_detail(html, url, content=content)
            if fetch_bn:
                try:
                    bn_html, _ = detail_fetcher.fetch_detail(url + "/bn")
                    bn = parse_detail(bn_html, url + "/bn")
                    _merge_bn(detail, bn)
                except FetchError:
                    pass  # Bangla variant optional
            _row, action = stage_detail(db, source, run, detail)
            ck.record_detail_done(db, run, url, staged=True)
            db.commit()
            logger.info("medex staged %s (%s)", detail.brand_name or detail.brand_name_bn, action)
            if auto_promote and principal is not None:
                # Phase 3C: promote this just-staged medicine immediately if it
                # classifies 'ready'. Bounded to a tiny sweep so it stays cheap
                # and commits inside the same per-detail checkpoint cadence.
                try:
                    from app.integrations.medex.promoter import promote_batch

                    promote_batch(db, principal, limit=1)
                    db.commit()
                except Exception:  # never let a promote error kill the collector
                    db.rollback()
                    logger.exception("medex auto-promote failed for %s", url)
        except FetchError as exc:
            ck.record_detail_error(db, run, url, exc.detail)
            db.commit()
        except Exception as exc:  # parse bug -> record as failed record
            logger.exception("medex parse error %s", url)
            ck.record_detail_error(db, run, url, f"parse: {exc}")
            db.commit()

    ck.finish(db, run, "completed")
    db.commit()
    return run


def resume_run(
    db: Session, fetcher: IndexFetcher, run: MedicineCatalogImportRun, **kwargs
) -> MedicineCatalogImportRun:
    """Resume an interrupted/paused run from its persisted checkpoint."""
    if run.status not in {"interrupted", "paused", "running", "failed"}:
        return run
    run.status = "pending"
    db.flush()
    return run_import(db, fetcher, run, **kwargs)

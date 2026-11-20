"""Operator CLI for the authorized MedEx collection.

Run inside the API package (``apps/api``) with the venv python and
``PYTHONPATH=.`` so ``app`` resolves:

    python -m app.integrations.medex.cli --index-pages 2 --details 30 --bn

Options
-------
--index-pages N   How many ``/brands`` index pages to scan for detail URLs.
--details N       Cap on detail pages fetched this run (pilot bound).
--bn              Also fetch each page's ``/bn`` variant for Bangla names.
--interval S      Seconds between requests (default 2.0 — conservative).
--resume ID       Resume an interrupted run by its UUID instead of starting new.

The command performs a *single, bounded, manual* collection — not a recurring
job. Everything lands in ``medicine_catalog_staging``; nothing is approved or
imported until a human reviews it in the workspace.
"""

from __future__ import annotations

import argparse
import logging
import sys
import uuid

from app.db.session import SessionLocal
from app.integrations.medex.client import MedexClient
from app.integrations.medex.importer import LiveFetcher, resume_run, run_import
from app.integrations.medex.repository import (
    create_run,
    get_or_create_source,
    staging_stats,
)
from app.models import MedicineCatalogImportRun

logger = logging.getLogger("shopflow.medex")


def _report(db, run: MedicineCatalogImportRun, source) -> None:
    stats = staging_stats(db, source.id)
    print("\n=== MedEx pilot report ===")
    print(f"run id        : {run.id}")
    print(f"status        : {run.status}")
    print(f"index pages   : up to {run.last_index_page} (last seen {run.last_page_seen})")
    print(f"discovered    : {run.discovered}")
    print(f"fetched       : {run.fetched}")
    print(f"staged        : {run.staged}")
    print(f"failed        : {run.failed}")
    print(f"pending queue : {len(run.pending_urls or [])}")
    print("---- staging totals ----")
    print(f"total staged  : {stats['total']}")
    print(f"by status     : {stats['by_status']}")
    print(f"missing price : {stats['missing_price']}")
    print(f"match cands   : {stats['match_candidates']}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Authorized MedEx catalog collector")
    p.add_argument("--index-start", type=int, default=1, help="first index page to scan")
    p.add_argument(
        "--index-pages",
        type=int,
        default=None,
        help="index pages to scan (omit = all discovered pages)",
    )
    p.add_argument(
        "--details",
        type=int,
        default=None,
        help="cap on detail fetches this run (omit = every discovered URL)",
    )
    p.add_argument("--scope", default="pilot", choices=["pilot", "full"], help="run scope label")
    p.add_argument("--bn", action="store_true", help="also fetch /bn Bangla variants")
    p.add_argument("--interval", type=float, default=2.0, help="seconds between requests")
    p.add_argument("--resume", type=str, default=None, help="resume run UUID")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    client = MedexClient(min_interval=args.interval)
    fetcher = LiveFetcher(client)
    try:
        with SessionLocal() as db:
            source = get_or_create_source(db)
            if args.resume:
                run = db.get(MedicineCatalogImportRun, uuid.UUID(args.resume))
                if run is None:
                    print(f"No run {args.resume}", file=sys.stderr)
                    return 2
                print(f"Resuming run {run.id} (status {run.status})…")
                run = resume_run(db, fetcher, run, fetch_bn=args.bn)
            else:
                run = create_run(
                    db,
                    source,
                    scope=args.scope,
                    index_start=args.index_start,
                    index_limit=args.index_pages,
                    detail_limit=args.details,
                )
                db.commit()
                print(
                    f"Starting {args.scope} run {run.id}: index {args.index_start}+"
                    f"{args.index_pages or 'all'} details≤{args.details or 'all'} "
                    f"bn={args.bn} interval={args.interval}s"
                )
                run = run_import(db, fetcher, run, fetch_bn=args.bn)
            _report(db, run, source)
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

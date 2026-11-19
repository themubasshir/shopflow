"""Development-only reset for the ShopFlow TEST database.

Drops and recreates ``shopflow_test`` so the test suite can run against a
clean, freshly migrated + seeded schema. This is the sanctioned replacement
for the ad-hoc Phase 2A cleanup script — it has hard safeguards so it can
NEVER touch ``shopflow_dev`` or any production database.

Usage (from apps/api, PYTHONPATH=apps/api):

    python ../../scripts/reset_test_db.py            # reset an explicitly configured test DB
    python ../../scripts/reset_test_db.py --yes      # skip the confirm prompt
    SHOPFLOW_TEST_DATABASE_URL=... python reset_test_db.py --yes
"""

from __future__ import annotations

import argparse
import os
import sys
from urllib.parse import urlparse

import psycopg


def _guard(url: str) -> str:
    """Return the test DB name, or abort if the URL looks non-test."""
    parsed = urlparse(url)
    name = parsed.path.removeprefix("/")
    if parsed.scheme not in {"postgresql", "postgresql+psycopg"} or name != "shopflow_test":
        sys.exit("REFUSING: expected a PostgreSQL database named exactly shopflow_test.")
    return name


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--yes", "-y", action="store_true", help="skip confirmation")
    args = ap.parse_args()

    url = os.environ.get("SHOPFLOW_TEST_DATABASE_URL")
    if not url:
        sys.exit("Set SHOPFLOW_TEST_DATABASE_URL to the dedicated shopflow_test database.")
    db = _guard(url)

    if not args.yes:
        ans = input(f"Drop and recreate TEST database {db!r}? [y/N] ").strip().lower()
        if ans not in {"y", "yes"}:
            print("aborted")
            return

    # Connect to the maintenance DB to drop/create.
    parsed = urlparse(url)
    admin = parsed._replace(path="/postgres").geturl()
    # strip the +psycopg driver scheme for the raw psycopg connection
    admin = admin.replace("postgresql+psycopg://", "postgresql://")

    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (db,),
        )
        conn.execute(f'DROP DATABASE IF EXISTS "{db}"')
        conn.execute(
            psycopg.sql.SQL("CREATE DATABASE {} OWNER {}").format(
                psycopg.sql.Identifier(db), psycopg.sql.Identifier(parsed.username)
            )
        )
    print(f"recreated {db!r}")
    print("now run:  alembic upgrade head   (against the test DB)")
    print("then:     python -m seeds.seed    (PYTHONPATH=apps/api, DATABASE_URL=test)")


if __name__ == "__main__":
    main()

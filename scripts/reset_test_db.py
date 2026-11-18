"""Development-only reset for the ShopFlow TEST database.

Drops and recreates ``shopflow_test`` so the test suite can run against a
clean, freshly migrated + seeded schema. This is the sanctioned replacement
for the ad-hoc Phase 2A cleanup script — it has hard safeguards so it can
NEVER touch ``shopflow_dev`` or any production database.

Usage (from apps/api, PYTHONPATH=apps/api):

    python ../../scripts/reset_test_db.py            # reset the default test DB
    python ../../scripts/reset_test_db.py --yes      # skip the confirm prompt
    SHOPFLOW_TEST_DATABASE_URL=... python reset_test_db.py --yes
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from urllib.parse import urlparse

import psycopg

DEFAULT_URL = (
    "postgresql+psycopg://shopflow_app:yXhH5B43O0hNgHlYZACAj1lIF6vyhM1D"
    "@localhost:5432/shopflow_test"
)

# Names this utility refuses to operate on, anywhere in the URL.
FORBIDDEN = ("shopflow_dev", "shopflow_prod", "prod", "production")


def _db_name(url: str) -> str:
    parsed = urlparse(url)
    return parsed.path.lstrip("/").split("/")[0]


def _guard(url: str) -> str:
    """Return the test DB name, or abort if the URL looks non-test."""
    name = _db_name(url)
    if "test" not in name:
        sys.exit(
            f"REFUSING: database {name!r} is not a *test* database. "
            "This utility only resets the dedicated test DB."
        )
    low = url.lower()
    for bad in FORBIDDEN:
        if re.search(rf"\b{re.escape(bad)}\b", low):
            sys.exit(f"REFUSING: URL appears to target {bad!r}: {url!r}")
    return name


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--yes", "-y", action="store_true", help="skip confirmation")
    args = ap.parse_args()

    url = os.environ.get("SHOPFLOW_TEST_DATABASE_URL", DEFAULT_URL)
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
        conn.execute(f'CREATE DATABASE "{db}" OWNER {parsed.username}')
    print(f"recreated {db!r}")
    print("now run:  alembic upgrade head   (against the test DB)")
    print("then:     python -m seeds.seed    (PYTHONPATH=apps/api, DATABASE_URL=test)")


if __name__ == "__main__":
    main()

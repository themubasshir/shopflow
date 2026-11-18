"""Test-suite fixtures — dedicated ``shopflow_test`` database isolation.

Phase 2B requires that automated tests can NEVER hit the development or
production database. Every session/connection built here is pointed at
``shopflow_test`` by overriding ``SessionLocal`` and the ``get_db`` dependency;
a hard guard aborts collection if the configured URL would touch anything else.
"""

from __future__ import annotations

import os
from collections.abc import Generator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# A dedicated database. The name is asserted below so a stray environment
# cannot silently redirect the suite at shopflow_dev / production.
TEST_DATABASE_URL = os.environ.get(
    "SHOPFLOW_TEST_DATABASE_URL",
    "postgresql+psycopg://shopflow_app:yXhH5B43O0hNgHlYZACAj1lIF6vyhM1D@localhost:5432/shopflow_test",
)


def _assert_is_test_db(url: str) -> None:
    if "shopflow_test" not in url:
        raise RuntimeError(
            f"Refusing to run tests against a non-test database: {url!r}. "
            "Set SHOPFLOW_TEST_DATABASE_URL to the dedicated test DB."
        )
    forbidden = ("shopflow_dev", "shopflow_prod", "production")
    for bad in forbidden:
        if bad in url:
            raise RuntimeError(f"Test database URL must not target {bad!r}: {url!r}")


_assert_is_test_db(TEST_DATABASE_URL)

# Build an isolated engine/sessionmaker bound only to the test database and
# swap it into app.db.session BEFORE the app is imported by the tests.
test_engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
TestingSessionLocal = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)

import app.db.session as db_session  # noqa: E402

db_session.SessionLocal = TestingSessionLocal
db_session.engine = test_engine

from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402


def _override_get_db() -> Generator:
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


# Route every FastAPI get_db dependency through the test sessionmaker.
app.dependency_overrides[get_db] = _override_get_db


def _seed_once() -> None:
    """Seed the test database with the demo fixture set if it is empty."""
    import sys
    from pathlib import Path

    seeds_dir = Path(__file__).resolve().parents[3] / "database" / "seeds"
    sys.path.insert(0, str(seeds_dir))
    import seed as seed_mod  # type: ignore

    with TestingSessionLocal() as db:
        from sqlalchemy import select

        from app.models import Shop

        if db.scalar(select(Shop).limit(1)) is None:
            seed_mod.seed(db)


@pytest.fixture(scope="session", autouse=True)
def _prepare_test_database():
    """Apply the seed exactly once per test run, against shopflow_test only."""
    with test_engine.connect() as conn:
        # Touch a known table to surface "database not migrated" early.
        conn.execute(text("SELECT 1 FROM shops LIMIT 1"))
    _seed_once()
    yield


@pytest.fixture
def db_session_test():
    """A direct Session bound to shopflow_test for service-level tests."""
    with TestingSessionLocal() as session:
        yield session


@pytest.fixture
def anyio_backend():
    return "asyncio"

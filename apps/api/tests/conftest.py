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
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.config import settings


def _test_database_url() -> str:
    configured = os.getenv("SHOPFLOW_TEST_DATABASE_URL")
    if configured:
        url = make_url(configured)
    else:
        local = make_url(settings.database_url)
        if local.host not in {"localhost", "127.0.0.1", "::1"} or local.database not in {
            "shopflow_dev",
            "shopflow_test",
        }:
            raise RuntimeError(
                "Set SHOPFLOW_TEST_DATABASE_URL to a dedicated shopflow_test database."
            )
        url = local.set(database="shopflow_test")
    if url.get_backend_name() != "postgresql" or url.database != "shopflow_test":
        raise RuntimeError("Tests require a PostgreSQL database named exactly shopflow_test.")
    if {"dbname", "database", "service", "servicefile"} & url.query.keys():
        raise RuntimeError(
            "Test database URL cannot override the target database via query parameters."
        )
    return url.render_as_string(hide_password=False)


TEST_DATABASE_URL = _test_database_url()

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
        if conn.scalar(text("SELECT current_database()")) != "shopflow_test":
            raise RuntimeError("Refusing to use a connection outside shopflow_test.")
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

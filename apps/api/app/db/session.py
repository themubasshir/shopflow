from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    echo=settings.database_echo,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def make_session_factory(database_url: str) -> sessionmaker[Session]:
    """Build an isolated Session factory for an explicit database URL.

    Used by the test-suite to point the app at ``shopflow_test`` so nothing
    the tests do can touch the development (or production) database.
    """
    test_engine = create_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
    )
    return sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

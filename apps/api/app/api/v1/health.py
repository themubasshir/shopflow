from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.schemas.common import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(db: Session = Depends(get_db)) -> HealthResponse:
    db_status = "ok"
    try:
        db.execute(text("SELECT 1"))
    except Exception:  # pragma: no cover - exercised in integration checks
        db_status = "unreachable"
    return HealthResponse(
        status="ok" if db_status == "ok" else "degraded",
        database=db_status,
        environment=settings.environment,
        version="0.1.0",
    )

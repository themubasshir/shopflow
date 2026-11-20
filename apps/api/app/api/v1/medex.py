"""MedEx catalog-import workspace API (Phase 3A).

Surfaces the staging area to the owner/manager review UI. Reads need
``catalog:read``; every state-changing action needs ``catalog:write``.

The collector endpoints operate on the staging tables only — promoting a
medicine into a real product goes through ``/staging/{id}/approve`` which
delegates to the normal zero-stock product-creation service.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_authenticated_principal
from app.db.session import get_db
from app.integrations.medex import approver, repository
from app.models import (
    MedicineCatalogImportRun,
    MedicineCatalogMatch,
    Product,
)
from app.schemas.medex import (
    ApproveBody,
    MatchBody,
    MatchOut,
    RejectBody,
    RunOut,
    SourceOut,
    StagingListOut,
    StagingOut,
    StatsOut,
)

router = APIRouter(prefix="/catalog/medex", tags=["medex-import"])

Db = Depends(get_db)
Auth = Depends(get_authenticated_principal)


def _source(db: Session):
    src = repository.get_or_create_source(db)
    return src


@router.get("/source", response_model=SourceOut)
def get_source(db: Session = Db, principal: Principal = Auth) -> SourceOut:
    principal.require("catalog:read")
    return _source(db)


# --- Runs -------------------------------------------------------------------


@router.get("/runs", response_model=list[RunOut])
def list_runs(
    db: Session = Db, principal: Principal = Auth, limit: int = Query(20, le=100)
) -> list[RunOut]:
    principal.require("catalog:read")
    src = _source(db)
    rows = db.scalars(
        select(MedicineCatalogImportRun)
        .where(MedicineCatalogImportRun.source_id == src.id)
        .order_by(MedicineCatalogImportRun.created_at.desc())
        .limit(limit)
    ).all()
    return [
        RunOut(
            **{c: getattr(r, c) for c in RunOut.model_fields if c != "pending_count"},
            pending_count=len(r.pending_urls or []),
        )
        for r in rows
    ]


# --- Staging -----------------------------------------------------------------


@router.get("/staging", response_model=StagingListOut)
def list_staging(
    db: Session = Db,
    principal: Principal = Auth,
    q: str | None = Query(None, max_length=80),
    manufacturer: str | None = Query(None, max_length=160),
    generic: str | None = Query(None, max_length=200),
    status: str | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, le=200),
) -> StagingListOut:
    principal.require("catalog:read")
    src = _source(db)
    rows, total = repository.list_staging(
        db,
        src.id,
        q=q,
        manufacturer=manufacturer,
        generic=generic,
        import_status=status,
        offset=offset,
        limit=limit,
    )
    return StagingListOut(rows=rows, total=total, offset=offset, limit=limit)


@router.get("/staging/filters", response_model=dict)
def staging_filters(db: Session = Db, principal: Principal = Auth) -> dict:
    """Distinct manufacturers + generics for the filter dropdowns."""
    principal.require("catalog:read")
    src = _source(db)
    from app.models import MedicineCatalogStaging as S

    mfrs = db.scalars(
        select(S.manufacturer)
        .where(S.source_id == src.id, S.manufacturer.is_not(None))
        .distinct()
        .order_by(S.manufacturer)
    ).all()
    gens = db.scalars(
        select(S.generic_name)
        .where(S.source_id == src.id, S.generic_name.is_not(None))
        .distinct()
        .order_by(S.generic_name)
    ).all()
    return {"manufacturers": list(mfrs), "generics": list(gens)}


@router.get("/staging/stats", response_model=StatsOut)
def staging_stats(db: Session = Db, principal: Principal = Auth) -> StatsOut:
    principal.require("catalog:read")
    src = _source(db)
    return StatsOut(**repository.staging_stats(db, src.id))


# --- Matches ------------------------------------------------------------------


@router.get("/matches", response_model=list[MatchOut])
def list_matches(
    db: Session = Db,
    principal: Principal = Auth,
    staging_id: uuid.UUID | None = Query(None),
    status: str = Query("pending"),
) -> list[MatchOut]:
    principal.require("catalog:read")
    src = _source(db)
    stmt = (
        select(MedicineCatalogMatch, Product)
        .join(Product, MedicineCatalogMatch.product_id == Product.id)
        .join(
            repository.MedicineCatalogStaging,
            MedicineCatalogMatch.staging_id == repository.MedicineCatalogStaging.id,
        )
        .where(repository.MedicineCatalogStaging.source_id == src.id)
    )
    if staging_id:
        stmt = stmt.where(MedicineCatalogMatch.staging_id == staging_id)
    if status:
        stmt = stmt.where(MedicineCatalogMatch.status == status)
    rows = db.execute(stmt.limit(200)).all()
    return [
        MatchOut(
            id=m.id,
            staging_id=m.staging_id,
            product_id=m.product_id,
            basis=m.basis,
            score=m.score,
            status=m.status,
            product_name_en=p.name_en,
            product_sku=p.sku,
        )
        for m, p in rows
    ]


# --- Actions ------------------------------------------------------------------


@router.post("/staging/approve", response_model=StagingOut)
def approve(body: ApproveBody, db: Session = Db, principal: Principal = Auth) -> StagingOut:
    row = approver.approve_staging(
        db,
        principal,
        body.staging_id,
        selling_price=body.selling_price,
        link_product_id=body.link_product_id,
    )
    return row


@router.post("/staging/reject", response_model=StagingOut)
def reject(body: RejectBody, db: Session = Db, principal: Principal = Auth) -> StagingOut:
    return approver.reject_staging(db, principal, body.staging_id)


@router.post("/matches/decide", response_model=MatchOut)
def decide_match(body: MatchBody, db: Session = Db, principal: Principal = Auth) -> MatchOut:
    m = approver.set_match_status(db, principal, body.match_id, confirm=body.confirm)
    p = db.get(Product, m.product_id)
    return MatchOut(
        id=m.id,
        staging_id=m.staging_id,
        product_id=m.product_id,
        basis=m.basis,
        score=m.score,
        status=m.status,
        product_name_en=p.name_en if p else None,
        product_sku=p.sku if p else None,
    )

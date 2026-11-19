from __future__ import annotations

import hashlib
import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.errors import IdempotencyConflictError
from app.models import IdempotencyRecord


def fingerprint(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def reserve_request(db: Session, shop_id: UUID, key: str, request_hash: str) -> IdempotencyRecord:
    """Reserve before taking business locks. A concurrent insert waits for commit or rollback."""
    db.execute(
        insert(IdempotencyRecord)
        .values(shop_id=shop_id, idempotency_key=key, request_fingerprint=request_hash)
        .on_conflict_do_nothing(index_elements=["shop_id", "idempotency_key"])
    )
    record = db.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.shop_id == shop_id, IdempotencyRecord.idempotency_key == key
        )
    )
    if record.request_fingerprint != request_hash:
        raise IdempotencyConflictError("Idempotency key was already used with a different request")
    return record

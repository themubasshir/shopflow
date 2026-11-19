from collections.abc import Callable
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import Principal
from app.core.errors import ConflictError
from app.services.idempotency import fingerprint, reserve_request

REFERENCE_CONFLICTS = {
    "uq_customer_refund_reference",
    "uq_supplier_credit_notes_reference",
    "uq_supplier_ledger_refund_reference",
    "uq_supplier_credit_notes_purchase_shipment",
}


def post_financial[Result: BaseModel](
    db: Session,
    principal: Principal,
    key: str,
    action: str,
    target: UUID,
    body: BaseModel,
    response_model: type[Result],
    operation: Callable[[], Result],
) -> Result:
    try:
        record = reserve_request(
            db,
            principal.shop_id,
            key,
            fingerprint(
                {"action": action, "target": str(target), "body": body.model_dump(mode="json")}
            ),
        )
        if record.response_body is None:
            result = operation()
            record.response_body = result.model_dump(mode="json")
        else:
            result = response_model.model_validate(
                {**record.response_body, "idempotent_replay": True}
            )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if getattr(getattr(exc.orig, "diag", None), "constraint_name", None) in REFERENCE_CONFLICTS:
            raise ConflictError("This reference or shipment was already recorded") from exc
        raise
    except Exception:
        db.rollback()
        raise
    return result

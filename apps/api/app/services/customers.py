from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import Principal
from app.core.errors import ConflictError, NotFoundError
from app.models import AuditLog, Customer, LoyaltyAccount
from app.schemas.customers import CustomerCreate, CustomerUpdate
from app.schemas.sales import CustomerOut


class DuplicateMobileError(ConflictError):
    code = "duplicate_mobile"


def get_customer(db: Session, shop_id: UUID, customer_id: UUID, *, lock=False) -> Customer:
    stmt = select(Customer).where(Customer.shop_id == shop_id, Customer.id == customer_id)
    if lock:
        stmt = stmt.with_for_update(key_share=True)
    customer = db.scalar(stmt)
    if customer is None:
        raise NotFoundError("Customer not found")
    return customer


def customer_summary(customer: Customer, points: int, *, can_read_financials: bool) -> CustomerOut:
    return CustomerOut(
        id=customer.id,
        name=customer.name,
        name_bn=customer.name_bn,
        phone=customer.phone,
        email=customer.email if can_read_financials else None,
        credit_limit=customer.credit_limit if can_read_financials else Decimal(0),
        is_active=customer.is_active,
        points_balance=points,
    )


def _save(db: Session) -> None:
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if (
            getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
            == "uq_customers_shop_id_phone"
        ):
            raise DuplicateMobileError("A customer with this mobile number already exists") from exc
        raise


def create_customer(db: Session, principal: Principal, body: CustomerCreate) -> CustomerOut:
    principal.require_write("customers:write")
    customer = Customer(shop_id=principal.shop_id, **body.model_dump())
    db.add(customer)
    _save(db)
    db.add(LoyaltyAccount(shop_id=principal.shop_id, customer_id=customer.id))
    db.add(
        AuditLog(
            shop_id=principal.shop_id,
            actor_user_id=principal.user_id,
            action="customer.create",
            entity_type="customer",
            entity_id=customer.id,
        )
    )
    result = customer_summary(customer, 0, can_read_financials=True)
    db.commit()
    return result


def update_customer(
    db: Session, principal: Principal, customer_id: UUID, body: CustomerUpdate
) -> CustomerOut:
    principal.require_write("customers:write")
    customer = get_customer(db, principal.shop_id, customer_id, lock=True)
    changes = body.model_dump(exclude_unset=True, mode="json")
    before = {"is_active": customer.is_active, "credit_limit": str(customer.credit_limit)}
    for name, value in body.model_dump(exclude_unset=True).items():
        setattr(customer, name, value)
    _save(db)
    db.add(
        AuditLog(
            shop_id=principal.shop_id,
            actor_user_id=principal.user_id,
            action="customer.update",
            entity_type="customer",
            entity_id=customer.id,
            before=before,
            after={
                "fields": sorted(changes),
                "is_active": customer.is_active,
                "credit_limit": str(customer.credit_limit),
            },
        )
    )
    points = db.scalar(
        select(LoyaltyAccount.points_balance).where(
            LoyaltyAccount.customer_id == customer.id, LoyaltyAccount.shop_id == principal.shop_id
        )
    )
    result = customer_summary(customer, points or 0, can_read_financials=True)
    db.commit()
    return result

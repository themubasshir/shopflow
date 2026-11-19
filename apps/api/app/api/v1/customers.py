from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_authenticated_principal
from app.core.errors import PermissionDeniedError
from app.db.session import get_db
from app.models import (
    Counter,
    Customer,
    CustomerLedgerEntry,
    Invoice,
    LoyaltyAccount,
    LoyaltyTransaction,
    Payment,
)
from app.schemas.common import Paginated
from app.schemas.customers import (
    CustomerBalanceOut,
    CustomerCreate,
    CustomerLedgerEntryOut,
    CustomerLoyaltyOut,
    CustomerPaymentOut,
    CustomerUpdate,
    DuePaymentCreate,
    DuePaymentOut,
    LoyaltyEntryOut,
)
from app.schemas.sales import CustomerOut, InvoiceOut
from app.services.customer_phone import phone_digits
from app.services.customers import create_customer, customer_summary, get_customer, update_customer
from app.services.loyalty import can_redeem
from app.services.loyalty_accounts import POLICY
from app.services.receivables import balance_query, collect_due_payment

router = APIRouter(prefix="/customers", tags=["customers"])
Db = Annotated[Session, Depends(get_db)]
Caller = Annotated[Principal, Depends(get_authenticated_principal)]
Limit = Annotated[int, Query(ge=1, le=200)]
Offset = Annotated[int, Query(ge=0)]


def _can_read_financials(principal: Principal) -> bool:
    return principal.assigned_counter_ids is None and "reports:read" in principal.permissions


def _financial_customer(db: Session, principal: Principal, customer_id: UUID) -> Customer:
    principal.require("customers:read")
    if not _can_read_financials(principal):
        raise PermissionDeniedError(
            "Customer financial history requires shop-wide financial access"
        )
    return get_customer(db, principal.shop_id, customer_id)


def _loyalty_account(db: Session, customer: Customer) -> LoyaltyAccount | None:
    return db.scalar(
        select(LoyaltyAccount).where(
            LoyaltyAccount.customer_id == customer.id, LoyaltyAccount.shop_id == customer.shop_id
        )
    )


def _count(db: Session, stmt) -> int:
    return db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0


@router.get("", response_model=Paginated[CustomerOut])
def list_customers(
    principal: Caller,
    db: Db,
    q: Annotated[str | None, Query(max_length=160)] = None,
    active: bool | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> Paginated[CustomerOut]:
    principal.require("customers:read")
    stmt = (
        select(Customer, LoyaltyAccount.points_balance)
        .outerjoin(
            LoyaltyAccount,
            (LoyaltyAccount.customer_id == Customer.id)
            & (LoyaltyAccount.shop_id == Customer.shop_id)
            & LoyaltyAccount.is_active.is_(True),
        )
        .where(Customer.shop_id == principal.shop_id)
    )
    if active is not None:
        stmt = stmt.where(Customer.is_active == active)
    if q and (query := q.strip()):
        mobile = phone_digits(query)
        if mobile.removeprefix("+").isdigit():
            for prefix in ("+880", "00880", "880", "0"):
                if mobile.startswith(prefix) and len(mobile) > len(prefix):
                    mobile = mobile[len(prefix) :]
                    break
        stmt = stmt.where(
            or_(
                Customer.name.icontains(query, autoescape=True),
                Customer.name_bn.icontains(query, autoescape=True),
                Customer.phone.icontains(mobile or query, autoescape=True),
            )
        )
    rows = db.execute(stmt.order_by(Customer.name, Customer.id).limit(limit).offset(offset))
    can_view = _can_read_financials(principal)
    can_view_points = "loyalty:read" in principal.permissions
    return Paginated(
        items=[
            customer_summary(
                c, (points or 0) if can_view_points else 0, can_read_financials=can_view
            )
            for c, points in rows
        ],
        total=_count(db, stmt),
        limit=limit,
        offset=offset,
    )


@router.post("", status_code=201, response_model=CustomerOut)
def add_customer(body: CustomerCreate, principal: Caller, db: Db) -> CustomerOut:
    return create_customer(db, principal, body)


@router.get("/{customer_id}", response_model=CustomerOut)
def customer_detail(customer_id: UUID, principal: Caller, db: Db) -> CustomerOut:
    principal.require("customers:read")
    customer = get_customer(db, principal.shop_id, customer_id)
    account = _loyalty_account(db, customer) if "loyalty:read" in principal.permissions else None
    return customer_summary(
        customer,
        account.points_balance if account and account.is_active else 0,
        can_read_financials=_can_read_financials(principal),
    )


@router.patch("/{customer_id}", response_model=CustomerOut)
def edit_customer(
    customer_id: UUID, body: CustomerUpdate, principal: Caller, db: Db
) -> CustomerOut:
    return update_customer(db, principal, customer_id, body)


@router.get("/{customer_id}/balance", response_model=CustomerBalanceOut)
def customer_balance(customer_id: UUID, principal: Caller, db: Db) -> CustomerBalanceOut:
    customer = _financial_customer(db, principal, customer_id)
    return CustomerBalanceOut(outstanding_due=db.scalar(balance_query(customer.id)))


@router.get("/{customer_id}/invoices", response_model=Paginated[InvoiceOut])
def customer_invoices(
    customer_id: UUID,
    principal: Caller,
    db: Db,
    limit: Limit = 50,
    offset: Offset = 0,
) -> Paginated[InvoiceOut]:
    customer = _financial_customer(db, principal, customer_id)
    principal.require("sales:read")
    stmt = (
        select(Invoice, Counter.code)
        .join(Counter, Counter.id == Invoice.counter_id)
        .where(
            Invoice.shop_id == principal.shop_id,
            Invoice.customer_id == customer.id,
        )
    )
    rows = db.execute(
        stmt.order_by(Invoice.created_at.desc(), Invoice.id).limit(limit).offset(offset)
    )
    return Paginated(
        items=[
            InvoiceOut(
                id=i.id,
                invoice_number=i.invoice_number,
                counter_code=code,
                customer_name=customer.name,
                status=i.status,
                subtotal=i.subtotal,
                discount_total=i.discount_total,
                loyalty_discount=i.loyalty_discount,
                tax_total=i.tax_total,
                total=i.total,
                paid_total=i.paid_total,
                due_total=i.due_total,
                finalized_at=i.finalized_at,
                created_at=i.created_at,
            )
            for i, code in rows
        ],
        total=_count(db, stmt),
        limit=limit,
        offset=offset,
    )


@router.get("/{customer_id}/payments", response_model=Paginated[CustomerPaymentOut])
def customer_payments(
    customer_id: UUID,
    principal: Caller,
    db: Db,
    limit: Limit = 50,
    offset: Offset = 0,
) -> Paginated[CustomerPaymentOut]:
    customer = _financial_customer(db, principal, customer_id)
    stmt = (
        select(Payment, Invoice.invoice_number)
        .join(Invoice, Invoice.id == Payment.invoice_id)
        .where(
            Invoice.shop_id == principal.shop_id,
            Invoice.customer_id == customer.id,
            Payment.method != "due",
        )
    )
    rows = db.execute(stmt.order_by(Payment.paid_at.desc(), Payment.id).limit(limit).offset(offset))
    return Paginated(
        items=[
            CustomerPaymentOut(
                id=p.id,
                invoice_id=p.invoice_id,
                invoice_number=number,
                method=p.method,
                amount=p.amount,
                reference=p.reference,
                paid_at=p.paid_at,
            )
            for p, number in rows
        ],
        total=_count(db, stmt),
        limit=limit,
        offset=offset,
    )


@router.get("/{customer_id}/statement", response_model=Paginated[CustomerLedgerEntryOut])
def customer_statement(
    customer_id: UUID,
    principal: Caller,
    db: Db,
    limit: Limit = 50,
    offset: Offset = 0,
) -> Paginated[CustomerLedgerEntryOut]:
    customer = _financial_customer(db, principal, customer_id)
    stmt = (
        select(
            CustomerLedgerEntry,
            Invoice.invoice_number,
            func.sum(CustomerLedgerEntry.amount)
            .over(order_by=CustomerLedgerEntry.id)
            .label("balance_after"),
        )
        .join(Invoice, Invoice.id == CustomerLedgerEntry.invoice_id)
        .where(
            Invoice.shop_id == principal.shop_id,
            CustomerLedgerEntry.customer_id == customer.id,
        )
    )
    rows = db.execute(stmt.order_by(CustomerLedgerEntry.id.desc()).limit(limit).offset(offset))
    return Paginated(
        items=[
            CustomerLedgerEntryOut(
                id=e.id,
                invoice_id=e.invoice_id,
                invoice_number=number,
                payment_id=e.payment_id,
                amount=e.amount,
                balance_after=balance,
                created_at=e.created_at,
            )
            for e, number, balance in rows
        ],
        total=_count(db, stmt),
        limit=limit,
        offset=offset,
    )


@router.post(
    "/{customer_id}/invoices/{invoice_id}/payments",
    status_code=201,
    response_model=DuePaymentOut,
    responses={200: {"model": DuePaymentOut, "description": "Idempotent replay"}},
)
def collect_payment(
    customer_id: UUID,
    invoice_id: UUID,
    body: DuePaymentCreate,
    response: Response,
    principal: Caller,
    db: Db,
    idempotency_key: Annotated[str, Header(min_length=8, max_length=120, alias="Idempotency-Key")],
) -> DuePaymentOut:
    result = collect_due_payment(db, principal, customer_id, invoice_id, body, idempotency_key)
    if result.idempotent_replay:
        response.status_code = 200
    return result


@router.get("/{customer_id}/loyalty", response_model=CustomerLoyaltyOut)
def customer_loyalty(customer_id: UUID, principal: Caller, db: Db) -> CustomerLoyaltyOut:
    principal.require("customers:read")
    principal.require("loyalty:read")
    customer = get_customer(db, principal.shop_id, customer_id)
    account = _loyalty_account(db, customer)
    return CustomerLoyaltyOut(
        points_balance=account.points_balance if account else 0,
        lifetime_earned=account.lifetime_earned
        if account and _can_read_financials(principal)
        else 0,
        lifetime_redeemed=account.lifetime_redeemed
        if account and _can_read_financials(principal)
        else 0,
        can_redeem=bool(
            customer.is_active
            and account
            and account.is_active
            and can_redeem(account.points_balance, POLICY)
        ),
        min_redeem_balance=POLICY.min_redeem_balance,
        redeem_step_points=POLICY.redeem_step_points,
        point_value_bdt=POLICY.point_value_bdt,
    )


@router.get("/{customer_id}/loyalty/transactions", response_model=Paginated[LoyaltyEntryOut])
def customer_loyalty_transactions(
    customer_id: UUID,
    principal: Caller,
    db: Db,
    limit: Limit = 50,
    offset: Offset = 0,
) -> Paginated[LoyaltyEntryOut]:
    customer = _financial_customer(db, principal, customer_id)
    principal.require("loyalty:read")
    stmt = (
        select(LoyaltyTransaction, Invoice.invoice_number)
        .outerjoin(
            Invoice,
            (Invoice.id == LoyaltyTransaction.invoice_id) & (Invoice.shop_id == principal.shop_id),
        )
        .join(LoyaltyAccount, LoyaltyAccount.id == LoyaltyTransaction.account_id)
        .where(
            LoyaltyAccount.customer_id == customer.id,
            LoyaltyAccount.shop_id == principal.shop_id,
        )
    )
    rows = db.execute(
        stmt.order_by(LoyaltyTransaction.ledger_sequence.desc()).limit(limit).offset(offset)
    )
    return Paginated(
        items=[
            LoyaltyEntryOut(
                id=t.id,
                invoice_id=t.invoice_id,
                invoice_number=number,
                transaction_type=t.transaction_type,
                points=t.points,
                balance_after=t.balance_after,
                created_at=t.created_at,
            )
            for t, number in rows
        ],
        total=_count(db, stmt),
        limit=limit,
        offset=offset,
    )

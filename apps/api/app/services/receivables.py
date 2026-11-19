from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import Principal
from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from app.models import AuditLog, Customer, CustomerLedgerEntry, Invoice, Payment
from app.schemas.customers import CustomerPaymentOut, DuePaymentCreate, DuePaymentOut
from app.schemas.sales import payment_status
from app.services.customers import get_customer
from app.services.idempotency import fingerprint, reserve_request
from app.services.loyalty_accounts import award_qualified_points, lock_account


class CreditLimitError(ConflictError):
    code = "credit_limit_exceeded"


class OverpaymentError(ValidationError):
    code = "overpayment"


def balance_query(customer_id, *, invoice_id: UUID | None = None):
    stmt = select(func.coalesce(func.sum(CustomerLedgerEntry.amount), 0)).where(
        CustomerLedgerEntry.customer_id == customer_id
    )
    if invoice_id is not None:
        stmt = stmt.where(CustomerLedgerEntry.invoice_id == invoice_id)
    return stmt


def check_credit_limit(db: Session, customer: Customer, amount: Decimal) -> None:
    if (
        customer.credit_limit
        and db.scalar(balance_query(customer.id)) + amount > customer.credit_limit
    ):
        raise CreditLimitError("This sale exceeds the customer's credit limit")


def collect_due_payment(
    db: Session,
    principal: Principal,
    customer_id: UUID,
    invoice_id: UUID,
    body: DuePaymentCreate,
    idempotency_key: str,
) -> DuePaymentOut:
    principal.require_write("sales:write")
    principal.require("customers:read")
    principal.require("reports:read")
    if principal.assigned_counter_ids is not None:
        raise PermissionDeniedError("Due collection requires shop-wide financial access")
    try:
        result = _collect_due_payment(db, principal, customer_id, invoice_id, body, idempotency_key)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return result


def _collect_due_payment(
    db: Session,
    principal: Principal,
    customer_id: UUID,
    invoice_id: UUID,
    body: DuePaymentCreate,
    idempotency_key: str,
) -> DuePaymentOut:
    payload = body.model_dump(mode="json")
    payload["amount"] = str(body.amount.quantize(Decimal("0.01")))
    record = reserve_request(
        db,
        principal.shop_id,
        idempotency_key,
        fingerprint(
            {
                "operation": "collect_due",
                "customer": str(customer_id),
                "invoice": str(invoice_id),
                "payment": payload,
            }
        ),
    )
    customer = get_customer(db, principal.shop_id, customer_id, lock=True)
    invoice = db.scalar(
        select(Invoice)
        .where(
            Invoice.id == invoice_id,
            Invoice.customer_id == customer.id,
            Invoice.shop_id == principal.shop_id,
            Invoice.status == "finalized",
        )
        .with_for_update(key_share=True)
    )
    if invoice is None:
        raise NotFoundError("Finalized customer invoice not found")
    if record.response_body is not None:
        return DuePaymentOut.model_validate({**record.response_body, "idempotent_replay": True})

    due = db.scalar(balance_query(customer.id, invoice_id=invoice.id))
    if due != invoice.due_total:
        raise ConflictError("Invoice and customer ledger balances disagree")
    if body.amount > due:
        raise OverpaymentError(
            "Payment cannot exceed the invoice balance", details={"due": str(due)}
        )
    invoice.paid_total += body.amount
    invoice.due_total -= body.amount
    points = 0
    if not invoice.due_total and invoice.loyalty_earn_base is not None:
        points = award_qualified_points(db, lock_account(db, customer), invoice, principal.user_id)

    payment = Payment(
        invoice_id=invoice.id,
        method=body.method,
        amount=body.amount,
        reference=body.reference,
        received_by=principal.user_id,
    )
    db.add(payment)
    db.flush()
    db.add(
        CustomerLedgerEntry(
            customer_id=customer.id,
            invoice_id=invoice.id,
            payment_id=payment.id,
            amount=-payment.amount,
        )
    )
    db.add(
        AuditLog(
            shop_id=principal.shop_id,
            actor_user_id=principal.user_id,
            action="invoice.collect_due",
            entity_type="invoice",
            entity_id=invoice.id,
            after={
                "payment_id": str(payment.id),
                "amount": str(payment.amount),
                "due": str(invoice.due_total),
            },
        )
    )
    db.flush()
    result = DuePaymentOut(
        payment=CustomerPaymentOut(
            **body.model_dump(),
            id=payment.id,
            invoice_id=invoice.id,
            invoice_number=invoice.invoice_number,
            paid_at=payment.paid_at,
        ),
        outstanding_due=db.scalar(balance_query(customer.id)),
        paid_total=invoice.paid_total,
        due_total=invoice.due_total,
        payment_status=payment_status(invoice.paid_total, invoice.due_total),
        loyalty_points_earned=points,
    )
    record.response_status = 201
    record.response_body = result.model_dump(mode="json")
    return result

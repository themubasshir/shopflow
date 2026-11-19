from collections import defaultdict
from decimal import Decimal
from uuid import UUID

from sqlalchemy import String, cast, func, select
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.orm import Session

from app.api.deps import Principal, assert_counter_allowed
from app.core.errors import NotFoundError, PermissionDeniedError
from app.models import (
    AuditLog,
    Counter,
    Customer,
    Invoice,
    InvoiceItem,
    LoyaltyTransaction,
    Payment,
    Shop,
)
from app.schemas.receipts import (
    InvoiceReceipt,
    ReceiptIdentity,
    ReceiptLine,
    ReceiptSettings,
    ReceiptTender,
)


def _shop(db: Session, shop_id: UUID) -> Shop:
    shop = db.get(Shop, shop_id)
    if shop is None:
        raise NotFoundError("Shop not found")
    return shop


def receipt_settings(shop: Shop) -> ReceiptSettings:
    if shop.receipt_settings is not None:
        return ReceiptSettings.model_validate(shop.receipt_settings)
    return ReceiptSettings(
        shop_name_en=shop.name_en,
        shop_name_bn=shop.name_bn,
        address=shop.address[:400] if shop.address else None,
        phone=shop.phone,
        tax_registration=shop.vat_number,
        heading_en=shop.receipt_header[:100] if shop.receipt_header else None,
        footer_en=shop.receipt_footer[:500] if shop.receipt_footer else None,
    )


def _require_owner(principal: Principal) -> None:
    principal.require_write("settings:write")
    if principal.role_code != "owner":
        raise PermissionDeniedError("Receipt settings require shop ownership")


def owner_receipt_settings(db: Session, principal: Principal) -> ReceiptSettings:
    _require_owner(principal)
    return receipt_settings(_shop(db, principal.shop_id))


def update_receipt_settings(
    db: Session, principal: Principal, body: ReceiptSettings
) -> ReceiptSettings:
    _require_owner(principal)
    shop = _shop(db, principal.shop_id)
    shop.receipt_settings = body.model_dump(mode="json")
    db.add(
        AuditLog(
            shop_id=shop.id,
            actor_user_id=principal.user_id,
            action="shop.receipt_settings",
            entity_type="shop",
            entity_id=shop.id,
        )
    )
    db.commit()
    return body


def mask_customer_phone(phone: str | None) -> str | None:
    digits = "".join(char for char in phone or "" if char.isdecimal())
    return "•••• " + digits[-4:] if len(digits) >= 8 else None


def capture_receipt_identity(
    db: Session,
    principal: Principal,
    counter: Counter,
    customer: Customer | None,
) -> dict:
    shop = _shop(db, principal.shop_id)
    return ReceiptIdentity(
        branding=receipt_settings(shop),
        currency=shop.currency,
        timezone=shop.timezone,
        counter_code=counter.code,
        counter_name_en=counter.name_en,
        counter_name_bn=counter.name_bn,
        cashier=principal.name,
        customer_name=customer.name if customer else None,
        customer_name_bn=customer.name_bn if customer else None,
        customer_phone_masked=mask_customer_phone(customer.phone) if customer else None,
        source="sale",
    ).model_dump(mode="json")


def get_invoice_receipt(db: Session, principal: Principal, invoice_id: UUID) -> InvoiceReceipt:
    principal.require("sales:read")
    # A single statement sees one PostgreSQL snapshot even when a collection commits concurrently.
    line_rows = (
        select(
            func.jsonb_agg(
                aggregate_order_by(
                    func.coalesce(InvoiceItem.receipt_details, func.jsonb_build_object()).op("||")(
                        func.jsonb_build_object(
                            "description",
                            InvoiceItem.description,
                            "quantity",
                            cast(InvoiceItem.quantity, String),
                            "unit_price",
                            cast(InvoiceItem.unit_price, String),
                            "line_discount",
                            cast(InvoiceItem.line_discount, String),
                            "line_total",
                            cast(InvoiceItem.line_total, String),
                        )
                    ),
                    InvoiceItem.receipt_details["position"].as_integer().nulls_last(),
                    InvoiceItem.created_at,
                    InvoiceItem.id,
                )
            )
        )
        .where(InvoiceItem.invoice_id == Invoice.id)
        .correlate(Invoice)
        .scalar_subquery()
    )
    tender_rows = (
        select(
            func.jsonb_agg(
                func.jsonb_build_object(
                    "method", Payment.method, "amount", cast(Payment.amount, String)
                )
            )
        )
        .where(Payment.invoice_id == Invoice.id, Payment.method != "due")
        .correlate(Invoice)
        .scalar_subquery()
    )
    closing_balance = (
        select(LoyaltyTransaction.balance_after)
        .where(LoyaltyTransaction.invoice_id == Invoice.id)
        .order_by(LoyaltyTransaction.ledger_sequence.desc())
        .limit(1)
        .correlate(Invoice)
        .scalar_subquery()
    )
    stmt = select(Invoice, line_rows, tender_rows, closing_balance).where(
        Invoice.id == invoice_id,
        Invoice.shop_id == principal.shop_id,
        Invoice.status.in_(("finalized", "voided", "refunded")),
    )
    row = db.execute(stmt).one_or_none()
    if row is None:
        raise NotFoundError("Saved invoice not found")
    invoice, items, payments, balance = row
    assert_counter_allowed(principal, invoice.counter_id)
    by_method = defaultdict(Decimal)
    for payment in payments or []:
        by_method[payment["method"]] += Decimal(payment["amount"])
    return InvoiceReceipt(
        id=invoice.id,
        invoice_number=invoice.invoice_number,
        issued_at=invoice.finalized_at,
        status=invoice.status,
        voided_at=invoice.voided_at,
        identity=ReceiptIdentity.model_validate(invoice.receipt_identity or {}),
        items=[ReceiptLine.model_validate(item) for item in items or []],
        subtotal=invoice.subtotal,
        discount_total=invoice.discount_total,
        loyalty_discount=invoice.loyalty_discount,
        tax_total=invoice.tax_total,
        total=invoice.total,
        paid_total=invoice.paid_total,
        due_total=invoice.due_total,
        payments=[ReceiptTender(method=k, amount=v) for k, v in sorted(by_method.items())],
        loyalty_points_redeemed=invoice.loyalty_points_redeemed,
        loyalty_points_earned=invoice.loyalty_points_earned,
        loyalty_points_balance=balance if balance is not None else invoice.receipt_points_balance,
    )

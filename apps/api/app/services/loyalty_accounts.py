from dataclasses import asdict
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import LoyaltyError
from app.models import (
    Customer,
    Invoice,
    LoyaltyAccount,
    LoyaltyRedemption,
    LoyaltyRule,
    LoyaltyTransaction,
)
from app.services.loyalty import (
    LoyaltyPolicy,
    discount_for_points,
    max_redeemable_points,
    points_earned,
)

POLICY = LoyaltyPolicy()


def rule_snapshot(db: Session, shop_id: UUID) -> dict:
    """Capture the confirmed v1 policy. Record the source if the active row matches it."""
    rule = db.scalar(
        select(LoyaltyRule).where(LoyaltyRule.shop_id == shop_id, LoyaltyRule.is_active.is_(True))
    )
    effective = asdict(POLICY)
    matches = (
        rule
        and rule.earn_on_eligible_category_only
        and all(getattr(rule, key) == value for key, value in effective.items())
    )
    return {
        **effective,
        "point_value_bdt": str(POLICY.point_value_bdt),
        "version": 1,
        "rule_id": str(rule.id) if matches else None,
        "earn_on_eligible_category_only": True,
    }


def lock_account(db: Session, customer: Customer, *, create: bool = False) -> LoyaltyAccount | None:
    # The caller owns the customer row lock, including when the account is absent.
    account = db.scalar(
        select(LoyaltyAccount)
        .where(
            LoyaltyAccount.customer_id == customer.id, LoyaltyAccount.shop_id == customer.shop_id
        )
        .with_for_update()
    )
    if account is None and create and customer.phone:
        account = LoyaltyAccount(customer_id=customer.id, shop_id=customer.shop_id)
        db.add(account)
        db.flush()
    return account if account and account.is_active else None


def redemption_discount(account: LoyaltyAccount | None, points: int, eligible: Decimal) -> Decimal:
    if not points:
        return Decimal("0.00")
    discount = discount_for_points(points, POLICY)
    if account is None or points > max_redeemable_points(account.points_balance, eligible, POLICY):
        raise LoyaltyError("Redemption exceeds the eligible amount or available points")
    return discount


def record_redemption(db: Session, account: LoyaltyAccount, invoice: Invoice, actor: UUID) -> None:
    points = invoice.loyalty_points_redeemed
    account.points_balance -= points
    account.lifetime_redeemed += points
    db.add_all(
        [
            LoyaltyRedemption(
                account_id=account.id,
                invoice_id=invoice.id,
                points_redeemed=points,
                discount_amount=invoice.loyalty_discount,
            ),
            LoyaltyTransaction(
                account_id=account.id,
                invoice_id=invoice.id,
                transaction_type="redeem",
                points=-points,
                balance_after=account.points_balance,
                created_by=actor,
            ),
        ]
    )


def award_qualified_points(
    db: Session, account: LoyaltyAccount | None, invoice: Invoice, actor: UUID
) -> int:
    if (
        account is None
        or invoice.due_total
        or invoice.loyalty_points_earned
        or invoice.loyalty_rule_snapshot is None
        or invoice.loyalty_earn_base is None
    ):
        return 0
    saved = invoice.loyalty_rule_snapshot
    policy = LoyaltyPolicy(
        points_per_100_bdt=saved["points_per_100_bdt"],
        min_redeem_balance=saved["min_redeem_balance"],
        redeem_step_points=saved["redeem_step_points"],
        point_value_bdt=Decimal(saved["point_value_bdt"]),
    )
    points = points_earned(invoice.loyalty_earn_base, policy)
    if points:
        account.points_balance += points
        account.lifetime_earned += points
        invoice.loyalty_points_earned = points
        db.add(
            LoyaltyTransaction(
                account_id=account.id,
                invoice_id=invoice.id,
                transaction_type="earn",
                points=points,
                balance_after=account.points_balance,
                created_by=actor,
            )
        )
    return points

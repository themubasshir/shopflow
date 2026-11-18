from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

from app.core.errors import LoyaltyError


@dataclass(frozen=True, slots=True)
class LoyaltyPolicy:
    """Confirmed ShopFlow loyalty rules.

    * Every full BDT 100 of eligible spending earns `points_per_100_bdt` points.
    * Redemption is unlocked only while the *current* balance is >= `min_redeem_balance`.
      Falling below the threshold locks redemption again.
    * Redemption happens in multiples of `redeem_step_points` points.
    * `redeem_step_points` points = `point_value_bdt * redeem_step_points` BDT discount.
    * Earned points are credited only after the bill/payment is finalised and can never
      be redeemed on the invoice that earned them.
    * Points never expire in v1.
    """

    points_per_100_bdt: int = 1
    min_redeem_balance: int = 300
    redeem_step_points: int = 100
    point_value_bdt: Decimal = Decimal("1.00")

    @property
    def earn_unit_bdt(self) -> Decimal:
        """Eligible spend required for one point (BDT 100 by default)."""
        if self.points_per_100_bdt <= 0:
            raise LoyaltyError("points_per_100_bdt must be positive")
        return (Decimal(100) / self.points_per_100_bdt).quantize(
            Decimal("0.01"), rounding=ROUND_DOWN
        )


def points_earned(eligible_amount_bdt: Decimal | str | int, policy: LoyaltyPolicy) -> int:
    """Whole points earned from eligible spend. Excess change does not carry over."""
    amount = Decimal(str(eligible_amount_bdt))
    if amount < 0:
        raise LoyaltyError("Eligible amount cannot be negative")
    unit = policy.earn_unit_bdt
    earned = int((amount / unit).to_integral_value(rounding=ROUND_DOWN))
    return max(earned, 0)


def can_redeem(current_balance: int, policy: LoyaltyPolicy) -> bool:
    """Redemption is unlocked only at an opening/current balance >= the threshold."""
    return current_balance >= policy.min_redeem_balance


def max_redeemable_points(
    current_balance: int, invoice_total_bdt: Decimal | str | int, policy: LoyaltyPolicy
) -> int:
    """Largest legal redemption for an invoice.

    Must be a multiple of the step, leave no over-discount, and only exist while
    the balance is above the unlock threshold. Points earned on *this* invoice are
    not part of `current_balance` yet, so they cannot be redeemed here.
    """
    if not can_redeem(current_balance, policy):
        return 0
    total = Decimal(str(invoice_total_bdt))
    if total <= 0:
        return 0
    step = policy.redeem_step_points
    max_by_balance = (current_balance // step) * step
    max_by_total = (
        int((total / (policy.point_value_bdt * step)).to_integral_value(rounding=ROUND_DOWN)) * step
    )
    return int(min(max_by_balance, max_by_total))


def discount_for_points(points: int, policy: LoyaltyPolicy) -> Decimal:
    if points <= 0 or points % policy.redeem_step_points != 0:
        raise LoyaltyError(
            f"Redemption must be a positive multiple of {policy.redeem_step_points} points"
        )
    return (policy.point_value_bdt * points).quantize(Decimal("0.01"))


def reverse_earned_points(earned: int, policy: LoyaltyPolicy) -> int:
    """Points to remove on return/refund (stored as a negative transaction)."""
    if earned < 0:
        raise LoyaltyError("earned points must be >= 0")
    return -earned

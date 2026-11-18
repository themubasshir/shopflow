from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.errors import LoyaltyError
from app.services.loyalty import (
    LoyaltyPolicy,
    can_redeem,
    discount_for_points,
    max_redeemable_points,
    points_earned,
    reverse_earned_points,
)

POLICY = LoyaltyPolicy()  # 1 point per BDT 100, unlock at 300, step 100, 1pt = BDT 1


class TestEarn:
    @pytest.mark.parametrize(
        ("amount", "expected"),
        [
            ("0", 0),
            ("99.99", 0),
            ("100", 1),
            ("250", 2),
            ("999", 9),
            ("1000", 10),
        ],
    )
    def test_full_hundreds_only(self, amount, expected):
        assert points_earned(Decimal(amount), POLICY) == expected

    def test_negative_rejected(self):
        with pytest.raises(LoyaltyError):
            points_earned(Decimal("-1"), POLICY)


class TestRedeemUnlock:
    @pytest.mark.parametrize(
        ("balance", "expected"),
        [(0, False), (299, False), (300, True), (400, True)],
    )
    def test_threshold(self, balance, expected):
        assert can_redeem(balance, POLICY) is expected

    def test_locks_again_below_threshold(self):
        # After redeeming 100 of a 400 balance the balance drops to 300 — still
        # unlocked at exactly the threshold. Dropping to 299 locks again.
        assert can_redeem(300, POLICY) is True
        assert can_redeem(299, POLICY) is False


class TestMaxRedeemable:
    def test_capped_by_balance_step(self):
        assert max_redeemable_points(400, Decimal("5000"), POLICY) == 400

    def test_capped_by_invoice_total(self):
        # 350 balance but bill is only BDT 220 -> max 200 points.
        assert max_redeemable_points(350, Decimal("220"), POLICY) == 200

    def test_locked_when_below_threshold(self):
        assert max_redeemable_points(299, Decimal("500"), POLICY) == 0

    def test_zero_for_empty_bill(self):
        assert max_redeemable_points(500, Decimal("0"), POLICY) == 0

    def test_same_invoice_points_not_spendable(self):
        # A 250-point balance can never redeem on this invoice regardless of
        # what it would earn: unlocked balance is required.
        assert max_redeemable_points(250, Decimal("1000"), POLICY) == 0


class TestDiscountValue:
    def test_step_discount(self):
        assert discount_for_points(100, POLICY) == Decimal("100.00")
        assert discount_for_points(300, POLICY) == Decimal("300.00")

    @pytest.mark.parametrize("points", [0, 50, 150, -100])
    def test_rejects_non_step_values(self, points):
        with pytest.raises(LoyaltyError):
            discount_for_points(points, POLICY)


class TestReturns:
    def test_reverse_earned(self):
        assert reverse_earned_points(7, POLICY) == -7

    def test_reverse_rejects_negative(self):
        with pytest.raises(LoyaltyError):
            reverse_earned_points(-1, POLICY)

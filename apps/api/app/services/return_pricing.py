from decimal import ROUND_DOWN, Decimal

from app.core.errors import ConflictError
from app.models import Invoice, InvoiceItem
from app.services.stock import MONEY, ZERO


def _split(amount: Decimal, weights: list[Decimal]) -> list[Decimal]:
    """Allocate saved invoice-level amounts to stable sale-time lines, to the cent."""
    total = sum(weights, ZERO)
    if not total:
        if amount:
            raise ConflictError("The original invoice cannot be allocated to its items")
        return [ZERO] * len(weights)
    traveled = previous = ZERO
    shares = []
    for weight in weights:
        traveled += weight
        cumulative = (amount * traveled / total).quantize(MONEY)
        shares.append(cumulative - previous)
        previous = cumulative
    return shares


def original_values(invoice: Invoice, items: list[InvoiceItem]) -> dict:
    """For every line return its non-loyalty tender, earn base and redemption value."""
    lines = [item.line_total for item in items]
    earned = [item.loyalty_eligible_amount for item in items]
    eligible = sum(earned, ZERO)
    manual = sum(lines, ZERO) + invoice.tax_total - invoice.total - invoice.loyalty_discount
    if not 0 <= manual <= sum(lines, ZERO):
        raise ConflictError("The original invoice totals cannot be reconciled")

    manual_eligible = min(manual, eligible)
    eligible_shares = _split(manual_eligible, earned)
    other_shares = _split(
        manual - manual_eligible, [v - e for v, e in zip(lines, earned, strict=True)]
    )
    eligible_after = [e - d for e, d in zip(earned, eligible_shares, strict=True)]
    if invoice.loyalty_discount > sum(eligible_after, ZERO):
        # Legacy sales may predate line eligibility snapshots.
        if invoice.loyalty_rule_snapshot is not None:
            raise ConflictError("The original loyalty discount cannot be reconciled")
        redemption_weights = [
            v - d - o for v, d, o in zip(lines, eligible_shares, other_shares, strict=True)
        ]
    else:
        redemption_weights = eligible_after
    redemption = _split(invoice.loyalty_discount, redemption_weights)
    tax = _split(invoice.tax_total, lines)
    return {
        item.id: (v - d - o - r + t, max(e - r, ZERO), r)
        for item, v, d, o, r, t, e in zip(
            items,
            lines,
            eligible_shares,
            other_shares,
            redemption,
            tax,
            eligible_after,
            strict=True,
        )
    }


def return_delta(value: Decimal, sold: Decimal, prior: Decimal, quantity: Decimal) -> Decimal:
    return (value * (prior + quantity) / sold).quantize(MONEY) - (value * prior / sold).quantize(
        MONEY
    )


def points_share(points: int, part: Decimal, whole: Decimal) -> int:
    if not whole or not points:
        return 0
    return min(points, int((points * part / whole).to_integral_value(rounding=ROUND_DOWN)))

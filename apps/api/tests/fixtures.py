"""Shared helpers for test fixtures that prepare opening balances.

Fixtures that create products or loyalty accounts must seed the append-only
ledgers, not just the physical projections. Reconciliation compares
``stock_on_hand`` / ``quantity_on_hand`` / ``points_balance`` against the sum
of recorded movements and opening balances, so a fixture that writes a
projection directly leaves the shop permanently inconsistent.

These helpers post the same ``opening`` movements and ``opening_points``
backfills the ``7f58b276a2e0`` and ``de452fa8b713`` migrations applied to
historical data. Opening stock is intentionally unvalued (no ``StockLot``,
``unit_cost`` NULL): fixture cost provenance is unknown, so the quantities
report as legacy unvalued inventory rather than fabricated valuation.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import LoyaltyAccount, MedicineBatch, Product, StockMovement

OPENING_NOTE = "Test fixture opening stock"


def post_opening_stock(db: Session, *products: Product, note: str = OPENING_NOTE) -> None:
    """Append ``opening`` movements covering fixture-seeded physical stock.

    Safe to call on any product: the movement is only written when the
    recorded ledger is short of the physical projection, matching the
    opening-reconciliation pattern in migration ``7f58b276a2e0``.
    """
    for product in products:
        db.flush()
        # Batch movements share product_id, so post batch openings first and
        # measure the remaining product-level shortfall afterwards — exactly
        # the order used by migration ``7f58b276a2e0`` and ``seeds/seed.py``.
        batches = list(
            db.scalars(select(MedicineBatch).where(MedicineBatch.product_id == product.id))
        )
        for batch in batches:
            batch_ledger = db.scalar(
                select(func.coalesce(func.sum(StockMovement.quantity), 0)).where(
                    StockMovement.batch_id == batch.id
                )
            )
            shortfall = Decimal(batch.quantity_on_hand) - Decimal(batch_ledger)
            if shortfall:
                db.add(
                    StockMovement(
                        shop_id=product.shop_id,
                        product_id=product.id,
                        batch_id=batch.id,
                        movement_type="opening",
                        quantity=shortfall,
                        note=note,
                    )
                )
        db.flush()
        product_ledger = db.scalar(
            select(func.coalesce(func.sum(StockMovement.quantity), 0)).where(
                StockMovement.product_id == product.id
            )
        )
        shortfall = Decimal(product.stock_on_hand) - Decimal(product_ledger)
        if shortfall:
            db.add(
                StockMovement(
                    shop_id=product.shop_id,
                    product_id=product.id,
                    movement_type="opening",
                    quantity=shortfall,
                    note=note,
                )
            )
    db.flush()


def set_opening_points(account: LoyaltyAccount, points: int) -> None:
    """Give a fixture loyalty account an opening balance that reconciles.

    ``points_balance`` must equal ``opening_points + Σ transactions``; a bare
    projection update without the opening backfill is exactly the legacy-data
    condition the reconciliation report flags.
    """
    account.points_balance = account.lifetime_earned = account.opening_points = points

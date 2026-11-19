"""Verify Phase 2E browser workflows and reconcile their PostgreSQL records."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from contextlib import ExitStack
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from verify_receipts import API, ROOT, WEB, port, stop, test_engine, wait_ready

from app.models import (
    Category,
    InvoiceBatchAllocation,
    InvoiceItem,
    MedicineBatch,
    Product,
    ProductUnit,
    Purchase,
    Shop,
    StockMovement,
    SupplierLedger,
)
from app.services.stock import shop_date


def fixtures(db: Session):
    shop = db.scalar(select(Shop).where(Shop.is_demo.is_(True)).order_by(Shop.created_at))
    if shop is None:
        raise RuntimeError("Seed shopflow_test before purchasing verification")
    category = db.scalar(
        select(Category.id).where(
            Category.shop_id == shop.id,
            Category.slug == "excluded",
        )
    )
    today = shop_date(db, shop.id)
    products = []
    for locale in ("en", "bn"):
        product = Product(
            shop_id=shop.id,
            category_id=category,
            sku=f"E-{locale}-{uuid4().hex[:8]}",
            name_en="Aster pharmacy sample",
            name_bn="অ্যাস্টার ফার্মেসির নমুনা",
            is_medicine=True,
            unit="piece",
            stock_on_hand=0,
            units=[ProductUnit(name="piece", name_bn="টি", selling_price=80, is_base=True)],
        )
        db.add(product)
        products.append(product)
    db.commit()
    return [
        {
            "locale": locale,
            "width": width,
            "product": str(product.id),
            "sku": product.sku,
            "expiry": (today + timedelta(days=20)).isoformat(),
            "manufacture": (today - timedelta(days=20)).isoformat(),
        }
        for locale, width, product in zip(("en", "bn"), (1440, 375), products, strict=True)
    ], products


def reconcile(db: Session, proofs):
    for proof in proofs:
        product = db.get(Product, UUID(proof["product"]))
        purchase = db.get(Purchase, UUID(proof["purchase"]))
        batch = db.scalar(select(MedicineBatch).where(MedicineBatch.product_id == product.id))
        moves = db.scalar(
            select(func.sum(StockMovement.quantity)).where(StockMovement.product_id == product.id)
        )
        batch_moves = db.scalar(
            select(func.sum(StockMovement.quantity)).where(StockMovement.batch_id == batch.id)
        )
        allocations = list(
            db.scalars(
                select(InvoiceBatchAllocation)
                .join(InvoiceItem, InvoiceItem.id == InvoiceBatchAllocation.invoice_item_id)
                .where(InvoiceItem.invoice_id == UUID(proof["invoice"]))
            )
        )
        balance = db.scalar(
            select(func.sum(SupplierLedger.amount)).where(SupplierLedger.purchase_id == purchase.id)
        )
        assert product.stock_on_hand == batch.quantity_on_hand == moves == batch_moves == 2
        assert batch.quantity_received == 3 and len(allocations) == 1
        assert allocations[0].quantity == 1 and allocations[0].batch_number == proof["batch"]
        assert purchase.received_total == Decimal("72") and balance == Decimal("52")
        print(
            f"{proof['locale']} {proof['width']}px, shopflow_test "
            f"{batch.batch_number}: 3 received, 1 allocated, 2 remaining, "
            f"supplier balance {balance}",
            flush=True,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--screenshots", type=Path, default=ROOT / ".local" / "purchasing-evidence")
    args = parser.parse_args()
    engine, url = test_engine()
    if not (WEB / ".next" / "BUILD_ID").exists():
        raise RuntimeError("Run npm run build in apps/web first")
    with Session(engine) as db, ExitStack() as stack:
        data, products = fixtures(db)

        def restore():
            db.expire_all()
            for product in products:
                product.is_active = False
            db.commit()

        stack.callback(restore)
        api_port, web_port = port(), port()
        while web_port == api_port:
            web_port = port()
        api_url = f"http://127.0.0.1:{api_port}"
        origin = f"http://127.0.0.1:{web_port}"
        env = dict(
            os.environ,
            DATABASE_URL=url,
            ENVIRONMENT="test",
            DEMO_MODE="false",
            NEXT_PUBLIC_API_URL=api_url + "/api/v1",
            SHOPFLOW_WEB_ORIGIN=origin,
            NEXT_TELEMETRY_DISABLED="1",
            PYTHONPATH=str(API),
        )
        scratch = ROOT / ".local"
        scratch.mkdir(exist_ok=True)
        tmp = Path(stack.enter_context(tempfile.TemporaryDirectory(dir=scratch)))
        fixture_file, results_file = tmp / "fixtures.json", tmp / "results.json"
        fixture_file.write_text(json.dumps(data), encoding="utf-8")

        def start(name, args, cwd, ready):
            logfile = scratch / f"purchasing-{name}.log"
            stream = stack.enter_context(logfile.open("w", encoding="utf-8"))
            child = subprocess.Popen(
                args, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT
            )
            stack.callback(stop, child)
            wait_ready(ready, child, logfile)

        start(
            "api",
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(api_port),
            ],
            API,
            api_url + "/api/v1/health",
        )
        start(
            "web",
            [
                "node",
                "node_modules/next/dist/bin/next",
                "start",
                "--hostname",
                "127.0.0.1",
                "--port",
                str(web_port),
            ],
            WEB,
            origin + "/en/login",
        )
        subprocess.run(
            [
                "node",
                "tests/purchasing-e2e.mjs",
                origin,
                str(fixture_file),
                str(results_file),
                str(args.screenshots.resolve()),
            ],
            cwd=WEB,
            check=True,
        )
        db.expire_all()
        reconcile(db, json.loads(results_file.read_text(encoding="utf-8")))


if __name__ == "__main__":
    main()

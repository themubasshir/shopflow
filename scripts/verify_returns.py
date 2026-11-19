"""Verify Phase 2F in Chromium and reconcile the browser's PostgreSQL transactions."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from contextlib import ExitStack
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

from app.api.deps import Principal
from app.core.permissions import ALL_PERMISSIONS
from app.models import (
    Category,
    Counter,
    Customer,
    CustomerLedgerEntry,
    CustomerRefundSettlement,
    CustomerReturn,
    CustomerReturnLine,
    Invoice,
    InvoiceBatchAllocation,
    LoyaltyAccount,
    LoyaltyTransaction,
    MedicineBatch,
    Payment,
    Product,
    ProductUnit,
    ReturnStockPortion,
    Shop,
    StockLot,
    StockMovement,
    SupplierLedger,
    User,
)
from app.schemas.purchasing import PurchaseWrite, ReceiveWrite, SupplierWrite
from app.schemas.sales import InvoiceCreate
from app.services.billing import finalize_invoice
from app.services.purchasing import create_purchase, receive_purchase, save_supplier
from app.services.reconciliation import discrepancies
from app.services.stock import available_stock, shop_date
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from verify_receipts import API, ROOT, WEB, port, stop, test_engine, wait_ready


def fixtures(db: Session):
    shop = db.scalar(
        select(Shop).where(Shop.is_demo.is_(True)).order_by(Shop.created_at)
    )
    if shop is None:
        raise RuntimeError("Seed shopflow_test before browser verification")
    user = db.scalar(
        select(User).where(
            User.shop_id == shop.id, User.email == "manager@shopflow.dev"
        )
    )
    counter = db.scalar(
        select(Counter.id).where(Counter.shop_id == shop.id, Counter.code == "C1")
    )
    actor = Principal(
        user_id=user.id,
        shop_id=shop.id,
        name=user.name,
        email=user.email,
        role_code="manager",
        permissions=frozenset(ALL_PERMISSIONS),
    )
    data = []
    for locale, width in (("en", 1440), ("bn", 375)):
        tag = uuid4().hex[:8].upper()
        category = Category(
            shop_id=shop.id,
            slug="returns-" + tag,
            name_en="Returns",
            name_bn="ফেরত",
            is_medicine=True,
            loyalty_eligible=True,
        )
        db.add(category)
        db.flush()
        product = Product(
            shop_id=shop.id,
            category_id=category.id,
            sku="F-" + tag,
            name_en="Aster medicine sample",
            name_bn="অ্যাস্টার ওষুধের নমুনা",
            is_medicine=True,
            loyalty_eligible=True,
            unit="piece",
            stock_on_hand=0,
            units=[
                ProductUnit(name="piece", name_bn="টি", selling_price=300, is_base=True)
            ],
        )
        customer = Customer(
            shop_id=shop.id,
            name="Aster returns account",
            name_bn="অ্যাস্টার ফেরত অ্যাকাউন্ট",
            phone="+8801" + str(uuid4().int)[-9:],
        )
        db.add_all([product, customer])
        db.flush()
        db.add(
            LoyaltyAccount(
                customer_id=customer.id,
                shop_id=shop.id,
                points_balance=350,
                lifetime_earned=350,
                opening_points=350,
            )
        )
        db.commit()
        supplier = save_supplier(
            db,
            actor,
            SupplierWrite(
                name="Aster Distribution " + tag,
                name_bn="অ্যাস্টার সরবরাহ " + tag,
                product_ids=[product.id],
            ),
        )
        batch_name = "ASTER-" + tag
        reference = "F-INV-" + tag
        purchase = create_purchase(
            db,
            actor,
            PurchaseWrite.model_validate(
                {
                    "supplier_id": supplier.id,
                    "supplier_invoice_number": reference,
                    "items": [
                        {
                            "product_id": product.id,
                            "quantity": "5",
                            "unit_cost": "50",
                            "batch_number": batch_name,
                            "expiry_date": shop_date(db, shop.id) + timedelta(days=35),
                        }
                    ],
                }
            ),
            str(uuid4()),
        )
        receive_purchase(
            db,
            actor,
            purchase.id,
            ReceiveWrite.model_validate(
                {
                    "items": [
                        {"purchase_item_id": purchase.items[0].id, "quantity": "5"},
                    ]
                }
            ),
            str(uuid4()),
        )
        sale = finalize_invoice(
            db,
            actor,
            InvoiceCreate.model_validate(
                {
                    "counter_id": counter,
                    "customer_id": customer.id,
                    "allow_due": True,
                    "redeem_points": 300,
                    "items": [{"product_id": product.id, "quantity": "3"}],
                    "payments": [{"method": "cash", "amount": "500"}],
                }
            ),
            str(uuid4()),
        )
        data.append(
            {
                "locale": locale,
                "width": width,
                "product": str(product.id),
                "product_en": product.name_en,
                "product_bn": product.name_bn,
                "invoice": str(sale.id),
                "batch": batch_name,
                "purchase": str(purchase.id),
                "purchase_reference": reference,
            }
        )
    return data


def reconcile(db: Session, proofs):
    for proof in proofs:
        invoice = db.get(Invoice, UUID(proof["invoice"]))
        product = db.get(Product, UUID(proof["product"]))
        row = db.get(CustomerReturn, UUID(proof["return_id"]))
        settlement = db.get(CustomerRefundSettlement, row.id)
        line = db.scalar(
            select(CustomerReturnLine).where(CustomerReturnLine.return_id == row.id)
        )
        portion = db.scalar(
            select(ReturnStockPortion).where(ReturnStockPortion.line_id == line.id)
        )
        source = db.get(StockMovement, portion.source_movement_id)
        batch = db.get(MedicineBatch, line.batch_id)
        lot = db.get(StockLot, source.stock_lot_id)
        allocation = db.scalar(
            select(InvoiceBatchAllocation).where(
                InvoiceBatchAllocation.invoice_item_id == line.invoice_item_id
            )
        )
        owing = db.scalar(
            select(func.sum(CustomerLedgerEntry.amount)).where(
                CustomerLedgerEntry.invoice_id == invoice.id
            )
        )
        collected = db.scalar(
            select(func.sum(Payment.amount)).where(Payment.invoice_id == invoice.id)
        )
        points = list(
            db.scalars(
                select(LoyaltyTransaction.points).where(
                    LoyaltyTransaction.invoice_id == invoice.id
                )
            )
        )
        account = db.scalar(
            select(LoyaltyAccount).where(
                LoyaltyAccount.customer_id == invoice.customer_id
            )
        )
        saleable = db.scalar(
            select(available_stock(shop_date(db, invoice.shop_id))).where(
                Product.id == product.id
            )
        )
        entries = dict(
            db.execute(
                select(SupplierLedger.kind, SupplierLedger.amount).where(
                    SupplierLedger.credit_note_id == UUID(proof["credit_id"])
                )
            ).all()
        )
        move_amount = db.scalar(
            select(func.sum(StockMovement.quantity)).where(
                StockMovement.product_id == product.id
            )
        )
        assert (invoice.total, invoice.paid_total, invoice.status, collected) == (
            600,
            500,
            "finalized",
            500,
        )
        assert (invoice.due_total, invoice.return_due_total, owing) == (0, 100, 0)
        assert (
            row.amount,
            row.due_reduction,
            row.refund_amount,
            settlement.method,
        ) == (200, 100, 100, "bkash")
        assert settlement.reference == "CUSTOMER-" + proof["batch"]
        assert sorted(points) == [-300, 4, 100] and account.points_balance == 154
        assert (
            invoice.loyalty_points_redeemed == 300
            and invoice.loyalty_points_earned == 4
        )
        assert (
            allocation.batch_id == batch.id
            and allocation.quantity == 3
            and portion.quantity == 1
        )
        assert batch.batch_number == proof["batch"]
        assert (
            product.stock_on_hand,
            batch.quantity_on_hand,
            lot.quantity_remaining,
            move_amount,
        ) == (2, 2, 2, 2)
        assert (
            product.held_quantity,
            batch.held_quantity,
            lot.held_quantity,
            saleable,
        ) == (1, 1, 1, 1)
        assert entries == {
            "credit": -50,
            "credit_offset": 30,
            "credit_application": -30,
            "refund": 10,
        }
        for entity in (
            invoice.id,
            product.id,
            row.id,
            account.id,
            batch.id,
            lot.id,
            allocation.id,
            UUID(proof["purchase"]),
            UUID(proof["credit_id"]),
        ):
            assert discrepancies(db, invoice.shop_id, None, entity, 50, 0).total == 0
        print(
            f"{proof['locale']} {proof['width']}px on shopflow_test: "
            "Tk100 due reduction, Tk100 completed refund, 100 restored points, "
            "4 points earned, 1 quarantined unit, Tk30 supplier credit applied, Tk10 received, "
            "zero scoped discrepancies",
            flush=True,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--screenshots", type=Path, default=ROOT / ".local" / "returns-evidence"
    )
    args = parser.parse_args()
    engine, url = test_engine()
    if not (WEB / ".next" / "BUILD_ID").exists():
        raise RuntimeError("Run npm run build in apps/web first")
    with Session(engine) as db, ExitStack() as stack:
        data = fixtures(db)

        def deactivate():
            db.rollback()
            for item in data:
                db.get(Product, UUID(item["product"])).is_active = False
            db.commit()

        stack.callback(deactivate)
        api_port, web_port = port(), port()
        while api_port == web_port:
            web_port = port()
        api_url, origin = f"http://127.0.0.1:{api_port}", f"http://127.0.0.1:{web_port}"
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

        def start(name, cmd, cwd, target):
            log = scratch / f"returns-{name}.log"
            stream = stack.enter_context(log.open("w", encoding="utf-8"))
            child = subprocess.Popen(
                cmd, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT
            )
            stack.callback(stop, child)
            wait_ready(target, child, log)

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
                "tests/returns-e2e.mjs",
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

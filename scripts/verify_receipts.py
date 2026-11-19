"""Run the receipt browser suite with local servers and the dedicated shopflow_test DB."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack
from datetime import date, timedelta
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen
from uuid import UUID, uuid4

from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    Category,
    Counter,
    Customer,
    LoyaltyAccount,
    MedicineBatch,
    Product,
    ProductUnit,
    Shop,
)

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "apps" / "api"
WEB = ROOT / "apps" / "web"

# Reuse the pytest fixture helpers so browser fixtures reconcile identically.
sys.path.insert(0, str(API / "tests"))
from fixtures import post_opening_stock  # noqa: E402


def test_engine():
    explicit = os.getenv("SHOPFLOW_TEST_DATABASE_URL")
    url = make_url(explicit or settings.database_url)
    if not explicit:
        if url.host not in {"localhost", "127.0.0.1", "::1"}:
            raise SystemExit("Set SHOPFLOW_TEST_DATABASE_URL explicitly.")
        url = url.set(database="shopflow_test")
    if (
        url.get_backend_name() != "postgresql"
        or url.database != "shopflow_test"
        or {"dbname", "database", "service", "servicefile"} & url.query.keys()
    ):
        raise SystemExit("Receipt tests require the isolated PostgreSQL shopflow_test database.")
    engine = create_engine(url)
    with engine.connect() as connection:
        if connection.scalar(text("SELECT current_database()")) != "shopflow_test":
            raise SystemExit("Refusing to write fixtures outside shopflow_test.")
    return engine, url.render_as_string(hide_password=False)


def fixtures(db: Session):
    shop = db.scalar(select(Shop).where(Shop.is_demo.is_(True)).order_by(Shop.created_at))
    if shop is None:
        raise SystemExit("Seed shopflow_test before running browser receipt verification.")
    categories = {
        category.slug: category.id
        for category in db.scalars(select(Category).where(Category.shop_id == shop.id))
    }
    counter = db.scalar(select(Counter).where(Counter.shop_id == shop.id, Counter.code == "C1"))
    session = uuid4().hex[:10]
    goods = Product(
        shop_id=shop.id,
        category_id=categories["grocery"],
        sku=f"D1-G-{session}",
        name_en="Aromatic rice from the northern harvest family pack",
        name_bn="উত্তরের নতুন মৌসুমের হাতে বাছাই করা সুগন্ধি চালের পারিবারিক প্যাক",
        unit="kg",
        stock_on_hand=50,
        units=[ProductUnit(name="kg", name_bn="কেজি", is_base=True, selling_price="187.25")],
    )
    medicine = Product(
        shop_id=shop.id,
        category_id=categories["excluded"],
        sku=f"D1-M-{session}",
        name_en="Extended-release medicine with a long descriptive name for repeat dispensing",
        name_bn="দীর্ঘ সময় ধরে কার্যকর ওষুধের বর্ধিত মুক্তির বিশেষ ফর্মুলার ট্যাবলেট",
        unit="pack",
        stock_on_hand=50,
        is_medicine=True,
        batches=[
            MedicineBatch(
                shop_id=shop.id,
                batch_number="DEMO-RX-1",
                expiry_date=date.today() + timedelta(days=365),
                quantity_on_hand=50,
                quantity_received=50,
            )
        ],
        units=[ProductUnit(name="pack", name_bn="প্যাক", is_base=True, selling_price="325.75")],
    )
    large = [
        Product(
            shop_id=shop.id,
            category_id=categories["grocery"],
            sku=f"D1-L-{session}-{number}",
            name_en=f"Thermal sample {number:02d} hand-sorted rice and red lentils refill packet",
            name_bn=f"পরীক্ষার পণ্য {number:02d} হাতে বাছাই করা সুগন্ধি চাল ও লাল মসুর ডালের প্যাকেট",
            unit="pack",
            stock_on_hand=15,
            units=[ProductUnit(name="pack", name_bn="প্যাক", is_base=True, selling_price="85.25")],
        )
        for number in range(1, 81)
    ]
    customer = Customer(
        shop_id=shop.id,
        name="Amina Rahman",
        name_bn="আমিনা রহমান",
        phone=f"+88016{uuid4().int % 100000000:08d}",
        loyalty_account=LoyaltyAccount(
            shop_id=shop.id, points_balance=400, lifetime_earned=400, opening_points=400
        ),
    )
    products = [goods, medicine, *large]
    db.add_all([*products, customer])
    db.flush()
    # Physical projections are seeded directly; reconcile the ledgers.
    post_opening_stock(db, *products)
    db.commit()
    return (
        {
            "shop": str(shop.id),
            "counter": str(counter.id),
            "customer": str(customer.id),
            "phone": customer.phone,
            "goods": str(goods.id),
            "goods_sku": goods.sku,
            "medicine": str(medicine.id),
            "large": [str(product.id) for product in large],
        },
        products,
        customer,
        shop.receipt_settings,
    )


def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def stop(process: subprocess.Popen) -> None:
    if process.poll() is None:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True)
        else:
            process.terminate()
    process.wait(timeout=10)


def wait_ready(url, process, log):
    deadline = time.monotonic() + 35
    while time.monotonic() < deadline and process.poll() is None:
        try:
            with urlopen(url, timeout=2) as response:
                if response.status == 200 and process.poll() is None:
                    return
        except (URLError, OSError):
            time.sleep(0.3)
    raise RuntimeError(f"Receipt test server did not start. See {log}.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--screenshots", type=Path, default=ROOT / ".local" / "receipt-evidence")
    parser.add_argument("--pdfs", type=Path, default=ROOT / ".local" / "receipt-evidence")
    args = parser.parse_args()
    engine, url = test_engine()
    if not (WEB / ".next" / "BUILD_ID").exists():
        raise SystemExit("Run npm run build in apps/web before browser verification.")
    with Session(engine) as db, ExitStack() as stack:
        data, products, customer, previous = fixtures(db)
        shop = db.get(Shop, UUID(data["shop"]))

        def restore():
            db.expire_all()
            shop.receipt_settings = previous
            customer.is_active = False
            for product in products:
                product.is_active = False
            db.commit()

        stack.callback(restore)
        api_port, web_port = port(), port()
        while web_port == api_port:
            web_port = port()
        api_url, web_url = f"http://127.0.0.1:{api_port}", f"http://127.0.0.1:{web_port}"
        env = dict(
            os.environ,
            DATABASE_URL=url,
            ENVIRONMENT="test",
            DEMO_MODE="false",
            NEXT_PUBLIC_API_URL=api_url + "/api/v1",
            SHOPFLOW_WEB_ORIGIN=web_url,
            NEXT_TELEMETRY_DISABLED="1",
            PYTHONPATH=str(API),
        )
        fixtures_dir = ROOT / ".local"
        fixtures_dir.mkdir(exist_ok=True)
        tmp = Path(stack.enter_context(tempfile.TemporaryDirectory(dir=fixtures_dir)))
        fixture_file = tmp / "fixtures.json"
        fixture_file.write_text(json.dumps(data), encoding="utf8")

        def start(name, command, cwd, ready_url):
            log_path = fixtures_dir / f"receipt-{name}.log"
            log = stack.enter_context(log_path.open("w", encoding="utf8"))
            process = subprocess.Popen(
                command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT
            )
            stack.callback(stop, process)
            wait_ready(ready_url, process, log_path)

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
            web_url + "/en/login",
        )
        subprocess.run(
            [
                "node",
                "tests/receipt-e2e.mjs",
                web_url,
                str(fixture_file),
                str(args.screenshots.resolve()),
                str(args.pdfs.resolve()),
            ],
            cwd=WEB,
            check=True,
        )


if __name__ == "__main__":
    main()

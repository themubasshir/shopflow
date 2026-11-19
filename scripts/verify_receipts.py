"""Run the receipt browser suite with local servers and the dedicated shopflow_test DB."""

from __future__ import annotations

import argparse
import json
import os
import re
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
        # Long enough that the bilingual receipt exceeds one PDF sheet, so the
        # multi-sheet split and its stitching are exercised, not just a tall page.
        for number in range(1, 201)
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


def check_pdf_margins(pdf_dir: Path) -> None:
    """Fail if any receipt text reaches past the printable width or a sheet is half empty.

    The body is 72 mm inside an 80 mm page (4 mm gutters). A span that touches
    the paper edge means the layout overflowed and the printer will cut the
    glyph, so this is the automated guard against the bilingual clipping
    regression.

    The vertical check catches a different, silent failure: a long receipt is
    split across several PDF sheets, and cropping a sheet from the wrong edge
    drops whole rows while still producing a plausible-looking document. A
    sheet that ends with a large blank tail is that signature (the last sheet is
    trimmed to the real content height, so it must end near its own bottom).

    PyMuPDF comes with the print-agent dependency set; when it is missing the
    check is skipped rather than silently passing.
    """
    try:
        import pymupdf
    except ImportError:  # pragma: no cover - depends on the local environment
        print("PDF margins: skipped (pymupdf is not installed)")
        return

    gutter_mm = 4.0
    tolerance_mm = 0.35
    # A page break can leave one un-splittable row's height empty; anything
    # larger than this means content was lost rather than deferred.
    max_blank_tail_mm = 60.0
    files = sorted(pdf_dir.glob("*.pdf"))
    if not files:
        raise SystemExit(f"No receipt PDFs found in {pdf_dir} to check.")
    widest = 0.0
    spans = 0
    sheets = 0
    for path in files:
        with pymupdf.open(path) as doc:
            for index, page in enumerate(doc, start=1):
                width_mm = page.rect.width * 25.4 / 72
                height_mm = page.rect.height * 25.4 / 72
                left_limit = gutter_mm - tolerance_mm
                right_limit = width_mm - gutter_mm + tolerance_mm
                lowest = 0.0
                for block in page.get_text("dict")["blocks"]:
                    for line in block.get("lines", []):
                        lowest = max(lowest, line["bbox"][3] * 25.4 / 72)
                        for span in line["spans"]:
                            x0 = span["bbox"][0] * 25.4 / 72
                            x1 = span["bbox"][2] * 25.4 / 72
                            if x0 < left_limit or x1 > right_limit:
                                raise SystemExit(
                                    f"{path.name} page {index}: {span['text']!r} spans "
                                    f"{x0:.2f}-{x1:.2f} mm, outside the printable "
                                    f"{gutter_mm:.0f}-{width_mm - gutter_mm:.2f} mm"
                                )
                            widest = max(widest, x1)
                            spans += 1
                blank_tail = height_mm - lowest
                if blank_tail > max_blank_tail_mm:
                    raise SystemExit(
                        f"{path.name} page {index}: content stops {blank_tail:.0f} mm "
                        f"above the bottom of a {height_mm:.0f} mm sheet — rows were "
                        "dropped when the receipt was split"
                    )
                sheets += 1
    print(
        f"PDF layout: {spans} spans across {sheets} sheet(s) in {len(files)} receipts stay "
        f"inside the printable width (max x1 {widest:.2f} mm) and fill every sheet."
    )


def check_long_receipt(pdf_dir: Path, expected_items: int) -> None:
    """Fail if a split receipt lost rows or left half a sheet blank.

    A receipt taller than one PDF sheet is split, and the last sheet is trimmed
    to the real content height. Cropping such a sheet from the wrong edge drops
    whole rows while still producing a plausible document, so this asserts every
    line item is present exactly once and that no sheet ends in a large blank.
    """
    try:
        import pymupdf
    except ImportError:  # pragma: no cover - depends on the local environment
        print("Long receipt: skipped (pymupdf is not installed)")
        return

    path = pdf_dir / "shopflow-receipt-bilingual-long.pdf"
    if not path.exists():
        raise SystemExit(f"Missing the long receipt PDF at {path}.")
    mm = 25.4 / 72
    max_blank_tail_mm = 60.0
    seen: dict[int, int] = {}
    with pymupdf.open(path) as doc:
        for index, page in enumerate(doc, start=1):
            lowest = 0.0
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    lowest = max(lowest, line["bbox"][3] * mm)
                    for span in line["spans"]:
                        match = re.search(r"Thermal sample (\d+)", span["text"])
                        if match:
                            number = int(match.group(1))
                            seen[number] = seen.get(number, 0) + 1
            blank_tail = page.rect.height * mm - lowest
            if blank_tail > max_blank_tail_mm:
                raise SystemExit(
                    f"{path.name} page {index}: content stops {blank_tail:.0f} mm above "
                    "the bottom of the sheet — rows were dropped when it was split"
                )
        sheets = doc.page_count
    missing = [n for n in range(1, expected_items + 1) if n not in seen]
    duplicated = sorted(n for n, count in seen.items() if count > 1)
    if missing or duplicated:
        raise SystemExit(
            f"{path.name}: {len(missing)} of {expected_items} line items missing "
            f"(first: {missing[:5]}), duplicated: {duplicated[:5]}"
        )
    if sheets < 2:
        raise SystemExit(f"{path.name}: expected a split receipt, got {sheets} sheet(s)")
    print(
        f"Long receipt: {expected_items} line items across {sheets} sheets, every item "
        "present exactly once and every sheet filled."
    )


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
        check_pdf_margins(args.pdfs)
        check_long_receipt(args.pdfs, len(data["large"]))


if __name__ == "__main__":
    main()

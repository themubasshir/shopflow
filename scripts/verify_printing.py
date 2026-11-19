"""Phase 2D-2 printer workflow: real browser, real queue, real print agent.

The runner starts loopback-only API and web servers on ``shopflow_test`` then
executes three stages against the same database:

1. ``queue``  — a browser owner registers a shared printer, routes two counters
   to it, queues a calibration test page and an invoice receipt.
2. ``agent``  — the actual ``printagent`` loop claims those jobs, exchanges the
   one-time document token for a render grant, fetches the canonical receipt PDF
   from the web route, rasterizes it and streams ESC/POS to a simulated printer
   that records every byte.
3. ``verify`` — the browser shows both jobs printed, and an explicit reprint
   creates a NEW job for the same invoice.

Nothing here proves a physical printer works; the byte stream is decoded back to
a bitmap and written as PNG evidence instead.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session
from verify_receipts import API, ROOT, WEB, port, stop, test_engine, wait_ready

from app.api.deps import Principal
from app.core.permissions import ALL_PERMISSIONS
from app.models import Counter, CounterPrinter, Invoice, Printer, PrintJob, Shop, User
from app.schemas.printing import PrinterCreate
from app.schemas.sales import InvoiceCreate
from app.services import printing as print_svc
from app.services.billing import finalize_invoice

AGENT = ROOT / "apps" / "agent"
sys.path.insert(0, str(AGENT))
from printagent.raster import pdf_to_raster  # noqa: E402

# Names this script gives its own printers. Only rows with these prefixes are
# ever removed, and only in the disposable shopflow_test database, so repeated
# runs do not pile up stale cards in the settings screenshot.
VERIFICATION_PREFIXES = ("Counter shared printer ", "Back-office printer ")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _clear_previous_runs(db: Session, shop_id: UUID) -> int:
    """Drop printers (and their jobs) left behind by earlier verification runs."""
    stale = db.scalars(
        select(Printer).where(
            Printer.shop_id == shop_id,
            or_(*[Printer.name.like(prefix + "%") for prefix in VERIFICATION_PREFIXES]),
        )
    ).all()
    if not stale:
        return 0
    ids = [printer.id for printer in stale]
    db.execute(delete(PrintJob).where(PrintJob.printer_id.in_(ids)))
    db.execute(delete(CounterPrinter).where(CounterPrinter.printer_id.in_(ids)))
    db.execute(delete(Printer).where(Printer.id.in_(ids)))
    db.commit()
    return len(ids)


def fixtures(db: Session) -> dict:
    shop = db.scalar(select(Shop).where(Shop.is_demo.is_(True)).order_by(Shop.created_at))
    if shop is None:
        raise SystemExit("Seed shopflow_test before running printer verification.")
    owner = db.scalar(
        select(User).where(User.shop_id == shop.id, User.email == "owner@shopflow.dev")
    )
    if owner is None:
        raise SystemExit("The demo shop needs its seeded owner account.")
    principal = Principal(
        user_id=owner.id,
        shop_id=shop.id,
        email=owner.email,
        name=owner.name,
        role_code="owner",
        permissions=frozenset(ALL_PERMISSIONS),
        assigned_counter_ids=None,
    )
    counters = db.scalars(
        select(Counter).where(Counter.shop_id == shop.id, Counter.code.in_(("C1", "C2")))
    ).all()
    if len(counters) != 2:
        raise SystemExit("The demo shop needs counters C1 and C2.")

    cleared = _clear_previous_runs(db, shop.id)
    if cleared:
        print(f"[verify] cleared {cleared} printer(s) from earlier runs", flush=True)

    tag = uuid4().hex[:8]
    printer, token = print_svc.create_printer(
        db,
        principal,
        PrinterCreate(
            name="Counter shared printer " + tag,
            transport="network",
            agent_id="agent-" + tag,
            paper_width_mm=80,
            dots_width=576,
            dpi=203,
            has_cutter=True,
            is_enabled=True,
            default_language="bilingual",
            config={"host": "127.0.0.1", "port": 9100},
        ),
    )
    c1 = next(c for c in counters if c.code == "C1")
    invoice = finalize_invoice(
        db,
        principal,
        InvoiceCreate.model_validate(
            {
                "counter_id": c1.id,
                "items": [{"product_id": str(_product(db, shop.id)), "quantity": "2"}],
                "payments": [{"method": "cash"}],
            }
        ),
        str(uuid4()),
    )
    db.commit()
    return {
        "shop": str(shop.id),
        "invoice": str(invoice.id),
        "printer_id": str(printer.id),
        "printer_name": printer.name,
        "agent_id": printer.agent_id,
        "agent_token": token,
        "second_printer_name": "Back-office printer " + tag,
        "second_agent_id": "agent-back-" + tag,
        "counters": [{"id": str(c.id), "code": c.code} for c in counters],
    }


def _product(db: Session, shop_id: UUID) -> UUID:
    """A stocked, sellable product so the fixture invoice can be finalized."""
    from app.models import Category, Product, ProductUnit
    from app.services.stock import available_stock, shop_date
    from fixtures import post_opening_stock

    product = db.scalar(
        select(Product)
        .where(Product.shop_id == shop_id, Product.is_active.is_(True))
        .where(available_stock(shop_date(db, shop_id)) >= 2)
        .order_by(Product.sku)
    )
    if product is not None:
        return product.id
    # Nothing sellable in the demo catalog: add one and reconcile its ledger.
    category = db.scalar(
        select(Category).where(Category.shop_id == shop_id).order_by(Category.slug)
    )
    if category is None:
        raise SystemExit("Seed product categories before running printer verification.")
    product = Product(
        shop_id=shop_id,
        category_id=category.id,
        sku="P2D2-" + uuid4().hex[:8],
        name_en="Printer check rice",
        name_bn="প্রিন্টার পরীক্ষার চাল",
        unit="kg",
        stock_on_hand=20,
        units=[ProductUnit(name="kg", name_bn="কেজি", is_base=True, selling_price="120")],
    )
    db.add(product)
    db.flush()
    post_opening_stock(db, product)
    db.commit()
    return product.id


# ---------------------------------------------------------------------------
# ESC/POS evidence
# ---------------------------------------------------------------------------


def decode_escpos(stream: bytes) -> dict:
    """Parse the GS v 0 bands back into a bitmap and summarize the stream.

    Proves the agent produced a real, calibrated monochrome page: every band is
    the printer's dot width, and the aggregate ink coverage is non-trivial.
    """
    assert stream[:2] == b"\x1b\x40", "missing ESC @ initialise"
    rows: list[bytes] = []
    bands = 0
    width = 0
    index = 2
    while index < len(stream):
        if stream[index : index + 3] == b"\x1dv0":
            bands += 1
            (xl, xh, yl, yh) = stream[index + 4 : index + 8]
            rowbytes = xl | (xh << 8)
            band_rows = yl | (yh << 8)
            width = width or rowbytes * 8
            assert rowbytes * 8 == width, "bands disagree on width"
            start = index + 8
            rows.append(stream[start : start + rowbytes * band_rows])
            index = start + rowbytes * band_rows
        elif stream[index] == 0x1B and stream[index + 1] == 0x64:
            index += 3  # ESC d n — feed
        elif stream[index] == 0x1D and stream[index + 1] == 0x56:
            index += 4  # GS V 66 0 — partial cut
        else:  # pragma: no cover - defensive
            raise AssertionError(f"unexpected ESC/POS byte at {index}: {stream[index]:#04x}")
    assert bands > 0, "no raster bands in the stream"
    body = b"".join(rows)
    height = len(body) // (width // 8)
    ink = sum(bin(byte).count("1") for byte in body)
    return {
        "width_dots": width,
        "height_dots": height,
        "bands": bands,
        "bytes": len(stream),
        "ink_ratio": round(ink / (width * height), 5),
        "cut": stream[-4:] == b"\x1dV\x42\x00",
        "bitmap": (width, height, body),
    }


def save_png(bitmap: tuple[int, int, bytes], path: Path) -> None:
    """Write the decoded 1-bit page as a grayscale PNG for visual evidence."""
    import pymupdf

    width, height, packed = bitmap
    rowbytes = width // 8
    gray = bytearray(width * height)
    for y in range(height):
        base = y * rowbytes
        out = y * width
        for x in range(width):
            bit = packed[base + (x >> 3)] & (0x80 >> (x & 7))
            gray[out + x] = 0 if bit else 255
    pix = pymupdf.Pixmap(pymupdf.csGRAY, width, height, bytes(gray), False)
    pix.save(str(path))
    pix = None


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------


def reconcile(db: Session, data: dict, result: dict, evidence: Path) -> None:
    assert result["phase"] == "verify", result
    proof = next(p for p in result["proofs"] if "reprint_job" in p)
    jobs = db.scalars(
        select(PrintJob)
        .where(PrintJob.printer_id == UUID(data["printer_id"]))
        .order_by(PrintJob.created_at)
    ).all()
    assert len(jobs) >= 3, f"expected test page, receipt and reprint; got {len(jobs)}"
    kinds = [job.kind for job in jobs]
    assert kinds.count("test_page") >= 1 and kinds.count("invoice") >= 2
    test_page = next(job for job in jobs if job.kind == "test_page")
    receipts = [job for job in jobs if job.kind == "invoice"]
    assert test_page.status == "completed"
    assert test_page.invoice_id is None and test_page.counter_id is None
    assert receipts[0].status == "completed"
    assert receipts[0].invoice_id == UUID(data["invoice"])
    assert receipts[0].attempts == 1
    assert receipts[0].completed_at is not None

    # The explicit reprint is a NEW pending job pointing at the completed one.
    reprint = next((job for job in receipts if job.reprint_of_job_id), None)
    assert reprint is not None, "explicit reprint did not create a linked job"
    assert reprint.id == UUID(proof["reprint_job"])
    assert reprint.reprint_of_job_id == receipts[0].id
    assert reprint.invoice_id == receipts[0].invoice_id
    assert reprint.status == "pending"

    # Printing is read-only against the financial record.
    invoice = db.get(Invoice, UUID(data["invoice"]))
    assert invoice.status == "finalized"
    assert invoice.paid_total == invoice.total
    assert invoice.due_total == 0
    assert receipts[0].counter_id == invoice.counter_id

    # The printer kept its identity; the raw token is never stored.
    printer = db.get(Printer, UUID(data["printer_id"]))
    assert printer.agent_id == data["agent_id"]
    assert printer.token_hash != data["agent_token"]
    second = db.scalar(select(Printer).where(Printer.name == data["second_printer_name"]))
    assert second is not None and second.default_language == "bn"

    stream = evidence.joinpath("escpos-stream.bin").read_bytes()
    shape = decode_escpos(stream)
    assert shape["width_dots"] == printer.dots_width, "stream width != printable dot width"
    assert shape["height_dots"] > 400
    assert shape["bands"] > 1
    assert shape["ink_ratio"] > 0.01
    assert shape["cut"], "cutter command missing for a printer with a cutter"
    save_png(shape["bitmap"], evidence.joinpath("printed-page.png"))

    # The strongest statement this harness can make without hardware: rasterize
    # the very PDF the browser downloaded and require the agent's bytes to be
    # bit-identical. Bengali shaping, width calibration and thresholding are all
    # therefore verified against the canonical document, not a lookalike.
    canonical = pdf_to_raster(
        evidence.joinpath("canonical-invoice.pdf").read_bytes(), printer.dots_width
    )
    printed_width, printed_height, printed = shape["bitmap"]
    rows = min(canonical.height, printed_height)
    assert canonical.width == printed_width, "canonical PDF and stream widths differ"
    differing = 0
    for y in range(rows):
        a = canonical.data[y * (canonical.width // 8) : (y + 1) * (canonical.width // 8)]
        b = printed[y * (printed_width // 8) : (y + 1) * (printed_width // 8)]
        differing += sum(bin(x ^ z).count("1") for x, z in zip(a, b, strict=True))
    assert differing == 0, f"{differing} pixels differ from the canonical PDF"

    print(
        "printing workflow on shopflow_test: "
        f"{len(jobs)} queued jobs, {test_page.kind} + {len(receipts)} receipt job(s), "
        "completed without retry, explicit reprint linked to the original, "
        f"{shape['bands']} ESC/POS bands at {shape['width_dots']} dots wide, "
        f"{shape['height_dots']} dots tall, ink {shape['ink_ratio']:.1%}, partial cut, "
        f"bit-identical to the canonical PDF over {rows} rows.",
        flush=True,
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=ROOT / ".local" / "printing-evidence")
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True)
    engine, url = test_engine()
    if not (WEB / ".next" / "BUILD_ID").exists():
        raise SystemExit("Run npm run build in apps/web before browser verification.")

    with Session(engine) as db, ExitStack() as stack:
        data = fixtures(db)
        scratch = ROOT / ".local"
        tmp = Path(stack.enter_context(tempfile.TemporaryDirectory(dir=scratch)))
        fixture_file, result_file = tmp / "fixtures.json", tmp / "results.json"
        fixture_file.write_text(json.dumps(data), encoding="utf-8")

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

        def start(name, command, cwd, ready_url):
            log_path = scratch / f"printing-{name}.log"
            log = stack.enter_context(log_path.open("w", encoding="utf-8"))
            child = subprocess.Popen(
                command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT
            )
            stack.callback(stop, child)
            wait_ready(ready_url, child, log_path)

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

        def browser(phase: str) -> None:
            subprocess.run(
                [
                    "node",
                    "tests/printing-e2e.mjs",
                    origin,
                    str(fixture_file),
                    str(result_file),
                    str(args.evidence.resolve()),
                    phase,
                ],
                cwd=WEB,
                check=True,
                timeout=300,
            )

        browser("queue")
        print("[verify] browser queue phase done", flush=True)

        # The real agent: claim → one-time document token → render grant → PDF →
        # raster → ESC/POS stream, exactly as it runs on a shop host.
        dump = args.evidence / "escpos-stream.bin"
        agent = subprocess.run(
            [
                sys.executable,
                "-m",
                "printagent",
                "simulate",
                "--agent-id",
                data["agent_id"],
                "--token",
                data["agent_token"],
                "--api",
                api_url + "/api/v1",
                "--web",
                origin,
                "--max-jobs",
                "2",
                "--dump",
                str(dump.resolve()),
            ],
            cwd=AGENT,
            env=dict(env, PYTHONPATH=str(AGENT)),
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
        )
        if agent.returncode != 0:
            raise SystemExit(f"print agent failed:\n{agent.stdout}\n{agent.stderr}")
        summary = json.loads(agent.stdout.strip().splitlines()[-1])
        assert summary["completed"] == 2, summary
        assert summary["failed"] == 0 and summary["uncertain"] == 0, summary
        assert dump.exists() and dump.stat().st_size > 20_000, "no ESC/POS stream captured"
        print(f"[verify] agent printed 2 jobs, {dump.stat().st_size} bytes captured", flush=True)

        browser("verify")
        print("[verify] browser verify phase done", flush=True)

        db.expire_all()
        reconcile(db, data, json.loads(result_file.read_text(encoding="utf-8")), args.evidence)


if __name__ == "__main__":
    main()

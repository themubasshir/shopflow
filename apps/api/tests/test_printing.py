"""Shared thermal printing tests (Phase 2D-2).

Each test builds an isolated shop with its own counters, printers and invoices,
then drives the queue through the public services. A simulated transport stands
in for hardware so the tests verify the queue, leasing, FIFO order, concurrency,
render grants and raster pipeline without a physical device.

Coverage: shared printer across many counters, FIFO ordering, concurrent-claim
protection, agent disconnection, lease expiry, failed + uncertain jobs,
explicit reprint, read-only financial safety, Bangla rasterization, printer
width calibration, long-receipt streaming, counter scoping and agent auth.
"""

from __future__ import annotations

import sys
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Principal
from app.core.errors import AuthenticationError, ConflictError, ValidationError
from app.core.permissions import ALL_PERMISSIONS
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models import (
    Category,
    Counter,
    Invoice,
    Printer,
    PrintJob,
    Product,
    ProductUnit,
    Role,
    Shop,
    User,
)
from app.schemas.printing import PrinterCapabilities, PrinterCreate, PrinterOut, PrinterUpdate
from app.services import printing as svc
from fixtures import post_opening_stock

AGENT_DIR = Path(__file__).resolve().parents[2] / "agent"
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from printagent.agent import AgentConfig, PrintAgent  # noqa: E402
from printagent.raster import (  # noqa: E402
    DEFAULT_THRESHOLD,
    density_threshold,
    pdf_to_escpos,
    pdf_to_raster,
)
from printagent.transport import NetworkTransport, SimulatedPrinter, TransportError  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _owner_principal(db: Session, shop: Shop, user_id: uuid.UUID | None = None) -> Principal:
    if user_id is None:
        user_id = db.scalar(select(User.id).where(User.shop_id == shop.id, User.name == "Owner"))
    return Principal(
        user_id=user_id,
        shop_id=shop.id,
        email="owner@x.dev",
        name="Owner",
        role_code="owner",
        permissions=frozenset(ALL_PERMISSIONS),
        assigned_counter_ids=None,
    )


@pytest.fixture()
def print_shop():
    """An isolated shop with two counters, a shared network printer and a
    cashier-scoped second counter.

    A real owner ``User`` backs every principal so ``print_jobs.requested_by``
    satisfies its FK. Each shop uses its own random agent id and invoice numbers
    so tests never collide even though fixture shops accumulate (the ledger
    tables are append-only, matching the other suite fixtures).
    """
    with SessionLocal() as db:
        shop = Shop(
            name_en="Print Test Shop",
            name_bn="মুদ্রণ পরীক্ষার দোকান",
            slug="print-" + uuid.uuid4().hex[:10],
            is_demo=False,
            is_active=True,
        )
        db.add(shop)
        db.flush()
        role = Role(
            shop_id=shop.id,
            code="owner",
            name_en="Owner",
            name_bn="মালিক",
            permissions=list(ALL_PERMISSIONS),
            is_system=True,
        )
        db.add(role)
        db.flush()
        owner_user = User(
            shop_id=shop.id,
            role_id=role.id,
            name="Owner",
            email="owner@print.test",
            password_hash=hash_password("OwnerPass#123"),
            preferred_locale="en",
            is_active=True,
        )
        c1 = Counter(shop_id=shop.id, code="C1", name_en="Front", name_bn="সামনে", sort_order=1)
        c2 = Counter(shop_id=shop.id, code="C2", name_en="Back", name_bn="পেছনে", sort_order=2)
        grocery = Category(
            shop_id=shop.id, slug="grocery", name_en="Grocery", name_bn="মুদি", loyalty_eligible=True
        )
        db.add_all([owner_user, c1, c2, grocery])
        db.flush()
        product = Product(
            shop_id=shop.id,
            category_id=grocery.id,
            sku="P-" + uuid.uuid4().hex[:8],
            name_en="Print rice",
            name_bn="চাল",
            unit="kg",
            stock_on_hand=Decimal(50),
            units=[
                ProductUnit(name="kg", name_bn="কেজি", is_base=True, selling_price=Decimal(100))
            ],
        )
        db.add(product)
        db.flush()
        post_opening_stock(db, product)
        agent_id = "agent-" + uuid.uuid4().hex[:8]
        agent_token = "tok-" + uuid.uuid4().hex
        printer = Printer(
            shop_id=shop.id,
            name="Counter printer",
            transport="network",
            agent_id=agent_id,
            token_hash=hash_password(agent_token),
            paper_width_mm=80,
            dots_width=576,
            dpi=203,
            has_cutter=True,
            is_enabled=True,
            default_language="bilingual",
            config={"host": "192.168.0.50", "port": 9100},
        )
        db.add(printer)
        db.commit()
        ctx = {
            "db": db,
            "shop": shop,
            "c1": c1,
            "c2": c2,
            "grocery": grocery,
            "product": product,
            "printer": printer,
            "owner": _owner_principal(db, shop, owner_user.id),
            "owner_user_id": owner_user.id,
            "agent_id": agent_id,
            "agent_token": agent_token,
        }
        yield ctx
        db.rollback()


def _invoice(db: Session, ctx, counter=None) -> Invoice:
    """Create a finalized invoice row directly (the print path only reads it)."""
    counter = counter or ctx["c1"]
    inv = Invoice(
        shop_id=ctx["shop"].id,
        counter_id=counter.id,
        invoice_number="PT-" + uuid.uuid4().hex[:8],
        status="finalized",
        subtotal=Decimal(100),
        total=Decimal(100),
        paid_total=Decimal(100),
        due_total=Decimal(0),
        receipt_identity={
            "branding": {"shop_name_en": "Print Test Shop", "shop_name_bn": "মুদ্রণ পরীক্ষার দোকান"},
            "currency": "BDT",
            "timezone": "Asia/Dhaka",
            "counter_code": counter.code,
            "counter_name_en": counter.name_en,
            "counter_name_bn": counter.name_bn,
            "source": "sale",
        },
        finalized_at=datetime.now(UTC),
    )
    db.add(inv)
    db.flush()
    return inv


# ---------------------------------------------------------------------------
# Printer management
# ---------------------------------------------------------------------------


def test_create_printer_returns_one_time_token(print_shop):
    ctx = print_shop
    with SessionLocal() as db:
        owner = _owner_principal(db, db.get(Shop, ctx["shop"].id))
        out, token = svc.create_printer(
            db,
            owner,
            PrinterCreate(
                name="Second",
                agent_id="agent-2",
                transport="network",
                config={"host": "192.168.0.60", "port": 9100},
            ),
        )
        assert out.agent_id == "agent-2"
        assert token and len(token) > 30  # shown once, never stored
        assert db.get(Printer, out.id).token_hash != token


def test_non_owner_cannot_manage_printer(print_shop):
    ctx = print_shop
    with SessionLocal() as db:
        mgr = Principal(
            user_id=uuid.uuid4(),
            shop_id=ctx["shop"].id,
            email="m@x.dev",
            name="M",
            role_code="manager",
            permissions=frozenset(p for p in ALL_PERMISSIONS if p != "settings:write"),
            assigned_counter_ids=None,
        )
        with pytest.raises(HTTPException):
            svc.create_printer(db, mgr, PrinterCreate(name="X", agent_id="a", transport="network"))


def test_staff_can_list_printers_but_never_see_the_agent_token(print_shop):
    ctx = print_shop
    with SessionLocal() as db:
        cashier = Principal(
            user_id=uuid.uuid4(),
            shop_id=ctx["shop"].id,
            email="c@x.dev",
            name="C",
            role_code="cashier",
            permissions=frozenset({"sales:read", "sales:write"}),
            assigned_counter_ids=None,
        )
        listed = svc.list_printers(db, cashier)
        assert [p.id for p in listed] == [ctx["printer"].id]
        # PrinterOut has no token/config field at all; the hash never leaks.
        serialized = listed[0].model_dump_json()
        assert ctx["agent_token"] not in serialized
        assert "token" not in PrinterOut.model_fields
        assert "config" not in PrinterOut.model_fields
        with pytest.raises(HTTPException):
            svc.create_printer(
                db, cashier, PrinterCreate(name="X", agent_id="cashier-agent", transport="network")
            )
        with pytest.raises(HTTPException):
            svc.list_printers(
                db,
                Principal(
                    user_id=uuid.uuid4(),
                    shop_id=ctx["shop"].id,
                    email="n@x.dev",
                    name="N",
                    role_code="cashier",
                    permissions=frozenset(),
                    assigned_counter_ids=None,
                ),
            )


# ---------------------------------------------------------------------------
# Enqueue + counter scoping
# ---------------------------------------------------------------------------


def test_enqueue_resolves_counter_default_printer(print_shop):
    ctx = print_shop
    with SessionLocal() as db:
        owner = _owner_principal(db, db.get(Shop, ctx["shop"].id))
        svc.assign_counter_printer(db, owner, ctx["c1"].id, ctx["printer"].id)
        inv = _invoice(db, ctx)
        job = svc.enqueue_print(db, owner, inv.id, None, None)
        assert job.printer_id == ctx["printer"].id
        assert job.counter_id == ctx["c1"].id
        assert job.status == "pending"


def test_enqueue_cashier_scoped_to_counter(print_shop):
    ctx = print_shop
    with SessionLocal() as db:
        inv = _invoice(db, ctx, counter=ctx["c2"])
        cashier = Principal(
            user_id=uuid.uuid4(),
            shop_id=ctx["shop"].id,
            email="c@x.dev",
            name="C",
            role_code="cashier",
            permissions=frozenset({"sales:read"}),
            assigned_counter_ids=frozenset({ctx["c1"].id}),  # not c2
        )
        with pytest.raises(HTTPException):
            svc.enqueue_print(db, cashier, inv.id, ctx["printer"].id, None)


def test_printing_never_mutates_invoice(print_shop):
    ctx = print_shop
    with SessionLocal() as db:
        owner = _owner_principal(db, db.get(Shop, ctx["shop"].id))
        inv = _invoice(db, ctx)
        snapshot = (inv.total, inv.status, inv.paid_total, inv.due_total)
        svc.enqueue_print(db, owner, inv.id, ctx["printer"].id, None)
        db.refresh(inv)
        assert (inv.total, inv.status, inv.paid_total, inv.due_total) == snapshot


def test_many_counters_share_one_printer_in_one_fifo_queue(print_shop):
    """Two counters routed to the same printer share its single queue: jobs
    interleave strictly by enqueue time and both keep their own counter id."""
    ctx = print_shop
    with SessionLocal() as db:
        owner = _owner_principal(db, db.get(Shop, ctx["shop"].id))
        svc.assign_counter_printer(db, owner, ctx["c1"].id, ctx["printer"].id)
        svc.assign_counter_printer(db, owner, ctx["c2"].id, ctx["printer"].id)
        shared = svc.list_printers(db, owner)[0]
        assert set(shared.counter_ids) == {ctx["c1"].id, ctx["c2"].id}

        first = svc.enqueue_print(db, owner, _invoice(db, ctx, ctx["c1"]).id, None, None)
        second = svc.enqueue_print(db, owner, _invoice(db, ctx, ctx["c2"]).id, None, None)
        third = svc.enqueue_print(db, owner, _invoice(db, ctx, ctx["c1"]).id, None, None)
        assert {first.printer_id, second.printer_id, third.printer_id} == {ctx["printer"].id}
        assert (first.counter_id, second.counter_id, third.counter_id) == (
            ctx["c1"].id,
            ctx["c2"].id,
            ctx["c1"].id,
        )

        printer = svc.authenticate_agent(db, ctx["agent_id"], ctx["agent_token"])
        claimed = []
        for _ in range(3):
            job, _t, _d = svc.claim_job(db, printer)
            claimed.append(job.id)
        assert claimed == [first.id, second.id, third.id]


# ---------------------------------------------------------------------------
# Agent auth + claim
# ---------------------------------------------------------------------------


def test_agent_auth_rejects_bad_token(print_shop):
    ctx = print_shop
    with SessionLocal() as db:
        printer = db.get(Printer, ctx["printer"].id)
        with pytest.raises(AuthenticationError):
            svc.authenticate_agent(db, printer.agent_id, "wrong-token")
        assert svc.authenticate_agent(db, printer.agent_id, ctx["agent_token"]).id == printer.id


def test_agent_scoped_to_own_printer(print_shop):
    ctx = print_shop
    with SessionLocal() as db:
        owner = _owner_principal(db, db.get(Shop, ctx["shop"].id))
        other_agent = "agent9-" + uuid.uuid4().hex[:8]
        other, _tok = svc.create_printer(
            db,
            owner,
            PrinterCreate(
                name="Other",
                agent_id=other_agent,
                transport="network",
                config={"host": "192.168.0.61", "port": 9100},
            ),
        )
        # A second agent resolves only to its own printer, never the shared one.
        printer9 = svc.authenticate_agent(db, other_agent, _tok)
        assert printer9.id == other.id
        assert printer9.id != ctx["printer"].id


# ---------------------------------------------------------------------------
# FIFO + concurrent claim
# ---------------------------------------------------------------------------


def test_fifo_claim_order(print_shop):
    ctx = print_shop
    with SessionLocal() as db:
        owner = _owner_principal(db, db.get(Shop, ctx["shop"].id))
        invs = [_invoice(db, ctx) for _ in range(3)]
        jobs = [svc.enqueue_print(db, owner, i.id, ctx["printer"].id, None) for i in invs]
        printer = svc.authenticate_agent(db, ctx["agent_id"], ctx["agent_token"])
        claimed = []
        for _ in range(3):
            job, _token, _doc = svc.claim_job(db, printer)
            claimed.append(job.id)
        assert claimed == [jobs[0].id, jobs[1].id, jobs[2].id]


def test_concurrent_claim_returns_distinct_rows(print_shop):
    ctx = print_shop
    with SessionLocal() as db:
        owner = _owner_principal(db, db.get(Shop, ctx["shop"].id))
        invs = [_invoice(db, ctx) for _ in range(4)]
        for i in invs:
            svc.enqueue_print(db, owner, i.id, ctx["printer"].id, None)

    results: list[uuid.UUID | None] = []
    import threading

    def worker():
        with SessionLocal() as db:
            printer = svc.authenticate_agent(db, ctx["agent_id"], ctx["agent_token"])
            job, _t, _d = svc.claim_job(db, printer)
            results.append(job.id if job else None)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    claimed = [r for r in results if r]
    assert len(claimed) == len(set(claimed)) == 4  # all distinct


# ---------------------------------------------------------------------------
# Lease lifecycle
# ---------------------------------------------------------------------------


def test_report_requires_live_claim_token(print_shop):
    ctx = print_shop
    with SessionLocal() as db:
        owner = _owner_principal(db, db.get(Shop, ctx["shop"].id))
        inv = _invoice(db, ctx)
        svc.enqueue_print(db, owner, inv.id, ctx["printer"].id, None)
        printer = svc.authenticate_agent(db, ctx["agent_id"], ctx["agent_token"])
        job, token, _d = svc.claim_job(db, printer)
        with pytest.raises(ConflictError):
            svc.complete_job(db, printer, job.id, "stale-token")
        svc.complete_job(db, printer, job.id, token)
        assert db.get(PrintJob, job.id).status == "completed"


def test_claimed_lease_expiry_returns_to_pending(print_shop):
    ctx = print_shop
    with SessionLocal() as db:
        owner = _owner_principal(db, db.get(Shop, ctx["shop"].id))
        inv = _invoice(db, ctx)
        svc.enqueue_print(db, owner, inv.id, ctx["printer"].id, None)
        printer = svc.authenticate_agent(db, ctx["agent_id"], ctx["agent_token"])
        job, _t, _d = svc.claim_job(db, printer)
        # Force the lease into the past, then reclaim.
        db.get(PrintJob, job.id).lease_until = datetime.now(UTC) - timedelta(seconds=1)
        db.flush()
        job2, _t2, _d2 = svc.claim_job(db, printer)
        assert job2.id == job.id
        assert db.get(PrintJob, job.id).status == "claimed"


def test_printing_lease_expiry_marks_uncertain_not_pending(print_shop):
    ctx = print_shop
    with SessionLocal() as db:
        owner = _owner_principal(db, db.get(Shop, ctx["shop"].id))
        inv = _invoice(db, ctx)
        svc.enqueue_print(db, owner, inv.id, ctx["printer"].id, None)
        printer = svc.authenticate_agent(db, ctx["agent_id"], ctx["agent_token"])
        job, token, _d = svc.claim_job(db, printer)
        svc.mark_printing(db, printer, job.id, token)
        db.get(PrintJob, job.id).lease_until = datetime.now(UTC) - timedelta(seconds=1)
        db.flush()
        svc.claim_job(db, printer)  # triggers lease reaping
        assert db.get(PrintJob, job.id).status == "uncertain"


# ---------------------------------------------------------------------------
# Failed / uncertain / retry / reprint
# ---------------------------------------------------------------------------


def test_failed_then_retry_then_complete(print_shop):
    ctx = print_shop
    with SessionLocal() as db:
        owner = _owner_principal(db, db.get(Shop, ctx["shop"].id))
        inv = _invoice(db, ctx)
        svc.enqueue_print(db, owner, inv.id, ctx["printer"].id, None)
        printer = svc.authenticate_agent(db, ctx["agent_id"], ctx["agent_token"])
        job, token, _d = svc.claim_job(db, printer)
        svc.fail_job(db, printer, job.id, token, "paper_jam", "paper jam at head")
        assert db.get(PrintJob, job.id).status == "failed"
        svc.retry_job(db, owner, job.id)
        job2, token2, _d2 = svc.claim_job(db, printer)
        svc.complete_job(db, printer, job2.id, token2)
        assert db.get(PrintJob, job.id).status == "completed"


def test_uncertain_job_cannot_be_retried(print_shop):
    ctx = print_shop
    with SessionLocal() as db:
        owner = _owner_principal(db, db.get(Shop, ctx["shop"].id))
        inv = _invoice(db, ctx)
        svc.enqueue_print(db, owner, inv.id, ctx["printer"].id, None)
        printer = svc.authenticate_agent(db, ctx["agent_id"], ctx["agent_token"])
        job, token, _d = svc.claim_job(db, printer)
        svc.mark_printing(db, printer, job.id, token)
        db.get(PrintJob, job.id).lease_until = datetime.now(UTC) - timedelta(seconds=1)
        db.flush()
        svc.claim_job(db, printer)
        with pytest.raises(ConflictError):
            svc.retry_job(db, owner, job.id)


def test_reprint_creates_new_job_referencing_invoice(print_shop):
    ctx = print_shop
    with SessionLocal() as db:
        owner = _owner_principal(db, db.get(Shop, ctx["shop"].id))
        inv = _invoice(db, ctx)
        svc.enqueue_print(db, owner, inv.id, ctx["printer"].id, None)
        printer = svc.authenticate_agent(db, ctx["agent_id"], ctx["agent_token"])
        job, token, _d = svc.claim_job(db, printer)
        svc.complete_job(db, printer, job.id, token)
        again = svc.enqueue_print(
            db, owner, inv.id, ctx["printer"].id, None, reprint_of_job_id=job.id
        )
        assert again.id != job.id
        assert again.invoice_id == inv.id
        assert again.reprint_of_job_id == job.id
        # The invoice is untouched — reprint never recreates the bill.
        assert db.get(Invoice, inv.id).status == "finalized"


# ---------------------------------------------------------------------------
# Hardware profile + shared-printer edge cases (Phase 2D-3)
# ---------------------------------------------------------------------------


def test_printer_hardware_profile_round_trips(print_shop):
    """Model, density, feed distance and capabilities persist and are visible to
    staff, while the connection detail stays write-only."""
    ctx = print_shop
    with SessionLocal() as db:
        owner = _owner_principal(db, db.get(Shop, ctx["shop"].id))
        out, _token = svc.create_printer(
            db,
            owner,
            PrinterCreate(
                name="Epson front desk",
                agent_id="agent-hw-" + uuid.uuid4().hex[:6],
                transport="network",
                device_model="Epson TM-T82X",
                density=6,
                feed_dots=120,
                capabilities=PrinterCapabilities(character=True),
                config={"host": "192.168.0.51", "port": 9100},
            ),
        )
        assert (out.device_model, out.density, out.feed_dots) == ("Epson TM-T82X", 6, 120)
        assert out.capabilities == {"raster": True, "character": True}
        row = db.get(Printer, out.id)
        assert row.config == {"host": "192.168.0.51", "port": 9100}


def test_printer_requires_transport_connection_detail(print_shop):
    ctx = print_shop
    with SessionLocal() as db:
        owner = _owner_principal(db, db.get(Shop, ctx["shop"].id))
        with pytest.raises(ValidationError) as missing_host:
            svc.create_printer(
                db,
                owner,
                PrinterCreate(name="No host", agent_id="agent-x1", transport="network"),
            )
        assert missing_host.value.details["field"] == "config.host"
        with pytest.raises(ValidationError) as bad_port:
            svc.create_printer(
                db,
                owner,
                PrinterCreate(
                    name="Bad port",
                    agent_id="agent-x2",
                    transport="network",
                    config={"host": "192.168.0.50", "port": 70000},
                ),
            )
        assert bad_port.value.details["field"] == "config.port"

        # Bluetooth is configurable but the agent refuses to drive it; the
        # gateway identifier is the minimum a future host needs.
        with pytest.raises(ValidationError):
            svc.create_printer(
                db,
                owner,
                PrinterCreate(name="BT", agent_id="agent-x3", transport="bluetooth"),
            )
        bluetooth, _token = svc.create_printer(
            db,
            owner,
            PrinterCreate(
                name="BT front desk",
                agent_id="agent-bt-" + uuid.uuid4().hex[:6],
                transport="bluetooth",
                config={"gateway_id": "front-desk-gateway", "host": "192.168.0.9"},
            ),
        )
        # Only the fields the transport uses are stored.
        assert db.get(Printer, bluetooth.id).config == {
            "gateway_id": "front-desk-gateway",
            "device_address": None,
        }


def test_character_only_printer_is_refused(print_shop):
    """The agent only emits ESC/POS raster bitmaps; a character-only device
    would silently lose Bengali shaping, so it cannot be registered."""
    ctx = print_shop
    with SessionLocal() as db:
        owner = _owner_principal(db, db.get(Shop, ctx["shop"].id))
        with pytest.raises(ValidationError) as refused:
            svc.create_printer(
                db,
                owner,
                PrinterCreate(
                    name="Character only",
                    agent_id="agent-chr",
                    transport="network",
                    capabilities=PrinterCapabilities(raster=False, character=True),
                    config={"host": "192.168.0.70", "port": 9100},
                ),
            )
        assert refused.value.details["field"] == "capabilities.raster"


def test_update_keeps_connection_detail_when_not_resent(print_shop):
    ctx = print_shop
    with SessionLocal() as db:
        owner = _owner_principal(db, db.get(Shop, ctx["shop"].id))
        renamed = svc.update_printer(db, owner, ctx["printer"].id, PrinterUpdate(name="Renamed"))
        assert renamed.name == "Renamed"
        assert db.get(Printer, ctx["printer"].id).config == {
            "host": "192.168.0.50",
            "port": 9100,
        }


def test_claim_snapshots_density_and_feed(print_shop):
    """A queued job keeps the calibration it was created with; editing the
    printer afterwards must not change an in-flight receipt."""
    ctx = print_shop
    with SessionLocal() as db:
        owner = _owner_principal(db, db.get(Shop, ctx["shop"].id))
        svc.update_printer(db, owner, ctx["printer"].id, PrinterUpdate(density=7, feed_dots=140))
        svc.enqueue_print(db, owner, _invoice(db, ctx).id, ctx["printer"].id, None)
        printer = svc.authenticate_agent(db, ctx["agent_id"], ctx["agent_token"])
        job, token, document = svc.claim_job(db, printer)
        view = svc.claimed_job_view(db, job, token, document)
        assert (view.density, view.feed_dots) == (7, 140)

        svc.update_printer(db, owner, ctx["printer"].id, PrinterUpdate(density=2, feed_dots=10))
        db.refresh(job)
        assert (job.density, job.feed_dots) == (7, 140)


def test_disabled_printer_stops_claiming_and_resumes(print_shop):
    """Deactivating a printer must stop its agent immediately; queued work stays
    queued (nothing is silently dropped) and resumes when it is re-enabled."""
    ctx = print_shop
    with SessionLocal() as db:
        owner = _owner_principal(db, db.get(Shop, ctx["shop"].id))
        queued = svc.enqueue_print(db, owner, _invoice(db, ctx).id, ctx["printer"].id, None)
        svc.update_printer(db, owner, ctx["printer"].id, PrinterUpdate(is_enabled=False))
        with pytest.raises(AuthenticationError):
            svc.authenticate_agent(db, ctx["agent_id"], ctx["agent_token"])
        assert db.get(PrintJob, queued.id).status == "pending"

        svc.update_printer(db, owner, ctx["printer"].id, PrinterUpdate(is_enabled=True))
        printer = svc.authenticate_agent(db, ctx["agent_id"], ctx["agent_token"])
        claimed, _token, _document = svc.claim_job(db, printer)
        assert claimed.id == queued.id


def test_reassignment_keeps_queued_jobs_on_their_printer(print_shop):
    """Moving a counter to another printer only affects future jobs."""
    ctx = print_shop
    with SessionLocal() as db:
        owner = _owner_principal(db, db.get(Shop, ctx["shop"].id))
        second, _token = svc.create_printer(
            db,
            owner,
            PrinterCreate(
                name="Second",
                agent_id="agent-re-" + uuid.uuid4().hex[:6],
                transport="network",
                config={"host": "192.168.0.52", "port": 9100},
            ),
        )
        svc.assign_counter_printer(db, owner, ctx["c1"].id, ctx["printer"].id)
        queued = svc.enqueue_print(db, owner, _invoice(db, ctx, ctx["c1"]).id, None, None)
        assert queued.printer_id == ctx["printer"].id

        svc.assign_counter_printer(db, owner, ctx["c1"].id, second.id)
        assert db.get(PrintJob, queued.id).printer_id == ctx["printer"].id
        fresh = svc.enqueue_print(db, owner, _invoice(db, ctx, ctx["c1"]).id, None, None)
        assert fresh.printer_id == second.id


def test_completed_job_is_never_claimed_twice(print_shop):
    """A finished job leaves the queue for good: the agent gets nothing on the
    next poll, so a receipt can never print twice from one job."""
    ctx = print_shop
    with SessionLocal() as db:
        owner = _owner_principal(db, db.get(Shop, ctx["shop"].id))
        queued = svc.enqueue_print(db, owner, _invoice(db, ctx).id, ctx["printer"].id, None)
        printer = svc.authenticate_agent(db, ctx["agent_id"], ctx["agent_token"])
        job, token, _document = svc.claim_job(db, printer)
        svc.complete_job(db, printer, job.id, token)

        again, _t, _d = svc.claim_job(db, printer)
        assert again is None
        assert db.get(PrintJob, queued.id).status == "completed"
        # The only way to print again is a deliberate reprint job.
        reprint = svc.enqueue_print(
            db, owner, queued.invoice_id, ctx["printer"].id, None, reprint_of_job_id=queued.id
        )
        assert reprint.id != queued.id
        assert reprint.reprint_of_job_id == queued.id


# ---------------------------------------------------------------------------
# Rasterization + transport (simulated)
# ---------------------------------------------------------------------------


_PDF_DIR = Path(__file__).resolve().parents[3] / "output" / "pdf"


def _sample_pdf() -> bytes:
    return (_PDF_DIR / "shopflow-receipt-bn.pdf").read_bytes()


def test_raster_calibrates_to_printer_dot_width():
    pdf = _sample_pdf()
    for dots in (576, 640):
        page = pdf_to_raster(pdf, dots)
        assert page.width == dots
        assert len(page.data) == ((dots + 7) // 8) * page.height


def test_escpos_stream_structure():
    pdf = _sample_pdf()
    stream = pdf_to_escpos(pdf, 576, has_cutter=True)
    assert stream[:2] == b"\x1b\x40"  # ESC @ init
    assert b"\x1dv0" in stream  # GS v 0 raster marker present
    assert stream[-4:-1] != b"" and stream[-4] == 0x1D  # ends with GS V cut


def test_long_receipt_produces_banded_stream():
    long_pdf = (_PDF_DIR / "shopflow-receipt-bilingual-long.pdf").read_bytes()
    stream = pdf_to_escpos(long_pdf, 576, has_cutter=True)
    # A ~17k-dot strip is split into many GS v 0 bands.
    assert stream.count(b"\x1dv0") > 20
    assert len(stream) > 1_000_000


def test_density_levels_map_to_a_bounded_threshold():
    """Level 4 must reproduce the pre-existing threshold byte-for-byte, and the
    other levels must stay inside a range that still burns legible text."""
    assert density_threshold(4) == DEFAULT_THRESHOLD
    levels = [density_threshold(level) for level in range(1, 9)]
    assert levels == sorted(levels, reverse=True)  # darker level → lower threshold
    assert all(80 <= threshold <= 200 for threshold in levels)


def test_density_and_feed_change_the_stream():
    pdf = _sample_pdf()
    neutral = pdf_to_escpos(pdf, 576, has_cutter=True, threshold=density_threshold(4))
    default = pdf_to_escpos(pdf, 576, has_cutter=True)
    assert neutral == default  # the default job is unchanged by this phase

    lighter = pdf_to_escpos(pdf, 576, has_cutter=True, threshold=density_threshold(2))
    darker = pdf_to_escpos(pdf, 576, has_cutter=True, threshold=density_threshold(7))
    assert lighter != neutral
    assert darker != neutral
    assert lighter.count(b"\x1dv0") == neutral.count(b"\x1dv0")  # same geometry
    assert darker.count(b"\x1dv0") == neutral.count(b"\x1dv0")

    # Feed distance only changes the ESC d parameter that precedes the cut.
    short = pdf_to_escpos(pdf, 576, has_cutter=True, feed_dots=0)
    long = pdf_to_escpos(pdf, 576, has_cutter=True, feed_dots=200)
    assert short[:-7] == long[:-7]  # identical raster
    assert short[-7:-4] == b"\x1bd\x00"
    assert long[-7:-4] == b"\x1bd\xc8"
    assert short[-4:] == long[-4:] == b"\x1dVB\x00"  # partial cut, unchanged


def test_simulated_transport_records_and_fails():
    sink: list[bytes] = []
    transport = SimulatedPrinter(sink=sink)
    transport.send(b"abc", {"host": "x"})
    assert sink == [b"abc"]
    transport.fail_next = True
    with pytest.raises(TransportError):
        transport.send(b"def", {"host": "x"})
    transport.disconnect_next = True
    with pytest.raises(TransportError):
        transport.send(b"ghi", {"host": "x"})


def test_network_transport_requires_host():
    transport = NetworkTransport()
    with pytest.raises(TransportError):
        transport.send(b"x", {})


# ---------------------------------------------------------------------------
# Full agent loop against a simulated print host
# ---------------------------------------------------------------------------


class _FakeAgentHttp:
    """Stands in for the API + web render route so the real ``PrintAgent`` loop
    can run end-to-end without a server or hardware. It delegates each protocol
    call to the real service layer and returns the sample receipt PDF bytes."""

    def __init__(self, agent_id: str, token: str) -> None:
        self.agent_id = agent_id
        self.token = token
        self.pdf = _sample_pdf()
        self.renders = 0

    def post_json(self, path: str, payload: dict) -> dict:
        with SessionLocal() as db:
            printer = svc.authenticate_agent(db, payload["agent_id"], payload["token"])
            if path.endswith("/agent/config"):
                cfg = svc.agent_config(db, printer)
                return {"transport": cfg.transport, "config": cfg.config}
            if path.endswith("/agent/claim"):
                job, claim_token, doc_token = svc.claim_job(db, printer)
                if job is None:
                    return {"job": None}
                view = svc.claimed_job_view(db, job, claim_token or "", doc_token or "")
                return {"job": view.model_dump(mode="json")}
            if path.endswith("/agent/document"):
                path_url, kind, invoice_id, language = svc.resolve_document(
                    db, printer, uuid.UUID(payload["job_id"]), payload["document_token"]
                )
                return {
                    "render_url": path_url,
                    "kind": kind,
                    "invoice_id": str(invoice_id) if invoice_id else None,
                    "language": language,
                }
            if path.endswith("/agent/report"):
                job_id = uuid.UUID(payload["job_id"])
                token = payload["claim_token"]
                if payload["outcome"] == "printing":
                    svc.mark_printing(db, printer, job_id, token)
                elif payload["outcome"] == "completed":
                    svc.complete_job(db, printer, job_id, token)
                else:
                    svc.fail_job(
                        db,
                        printer,
                        job_id,
                        token,
                        payload.get("error_code"),
                        payload.get("error_message"),
                    )
                return {"status": "ok"}
        raise AssertionError(f"unexpected agent path {path}")

    def fetch_bytes(self, path: str) -> bytes:
        assert "grant=" in path  # only the render-grant URL is ever fetched
        self.renders += 1
        return self.pdf


def _run_agent(ctx, transport) -> tuple[PrintAgent, _FakeAgentHttp]:
    http = _FakeAgentHttp(ctx["agent_id"], ctx["agent_token"])
    agent = PrintAgent(
        config=AgentConfig(agent_id=ctx["agent_id"], token=ctx["agent_token"]),
        transport=transport,
        http=http,
    )
    return agent, http


def test_agent_end_to_end_prints_and_reports_completed(print_shop):
    ctx = print_shop
    with SessionLocal() as db:
        owner = _owner_principal(db, db.get(Shop, ctx["shop"].id))
        inv = _invoice(db, ctx)
        job = svc.enqueue_print(db, owner, inv.id, ctx["printer"].id, None)

    sink: list[bytes] = []
    agent, http = _run_agent(ctx, SimulatedPrinter(sink=sink))
    assert agent.process_next() is True
    assert http.renders == 1  # the PDF was rendered exactly once
    assert sink and sink[0][:2] == b"\x1b\x40"  # ESC/POS init at the head
    with SessionLocal() as db:
        assert db.get(PrintJob, job.id).status == "completed"


def test_agent_disconnect_reports_failed_not_reprinted(print_shop):
    ctx = print_shop
    with SessionLocal() as db:
        owner = _owner_principal(db, db.get(Shop, ctx["shop"].id))
        inv = _invoice(db, ctx)
        job = svc.enqueue_print(db, owner, inv.id, ctx["printer"].id, None)

    transport = SimulatedPrinter(sink=[])
    transport.disconnect_next = True
    agent, _http = _run_agent(ctx, transport)
    assert agent.process_next() is True
    with SessionLocal() as db:
        stored = db.get(PrintJob, job.id)
        assert stored.status == "failed"
        assert stored.error_code == "transport_uncertain"
        assert stored.attempts == 1


# ---------------------------------------------------------------------------
# Printer test page (a first-class job with no invoice)
# ---------------------------------------------------------------------------


def test_test_page_job_runs_through_agent_without_invoice(print_shop):
    ctx = print_shop
    with SessionLocal() as db:
        owner = _owner_principal(db, db.get(Shop, ctx["shop"].id))
        job = svc.enqueue_test_page(db, owner, ctx["printer"].id, "bn")
        assert job.kind == "test_page"
        assert job.invoice_id is None
        assert job.language == "bn"

    sink: list[bytes] = []
    agent, http = _run_agent(ctx, SimulatedPrinter(sink=sink))
    assert agent.process_next() is True
    assert http.renders == 1
    assert sink and sink[0][:2] == b"\x1b\x40"
    with SessionLocal() as db:
        stored = db.get(PrintJob, job.id)
        assert stored.status == "completed"
        assert stored.invoice_id is None
        assert stored.counter_id is None


def test_test_page_requires_owner(print_shop):
    ctx = print_shop
    with SessionLocal() as db:
        cashier = Principal(
            user_id=uuid.uuid4(),
            shop_id=ctx["shop"].id,
            email="c@x.dev",
            name="C",
            role_code="cashier",
            permissions=frozenset({"sales:read", "sales:write"}),
            assigned_counter_ids=None,
        )
        with pytest.raises(HTTPException):
            svc.enqueue_test_page(db, cashier, ctx["printer"].id, None)


def test_test_page_grant_carries_no_invoice(print_shop):
    ctx = print_shop
    with SessionLocal() as db:
        owner = _owner_principal(db, db.get(Shop, ctx["shop"].id))
        svc.enqueue_test_page(db, owner, ctx["printer"].id, None)
        printer = svc.authenticate_agent(db, ctx["agent_id"], ctx["agent_token"])
        job, _t, doc = svc.claim_job(db, printer)
        _path, kind, invoice_id, language = svc.resolve_document(db, printer, job.id, doc or "")
        assert kind == "test_page"
        assert invoice_id is None
        assert language == ctx["printer"].default_language


def test_invoice_grant_cannot_render_a_foreign_invoice():
    from app.core.security import TokenError, create_render_grant, decode_render_grant

    grant = create_render_grant(kind="invoice", language="en", job_id="j1")
    # An invoice grant without an invoice_id is rejected outright.
    with pytest.raises(TokenError):
        decode_render_grant(grant)
    # A test-page grant naming an invoice is rejected too (no arbitrary render).
    with pytest.raises(TokenError):
        decode_render_grant(
            create_render_grant(
                kind="test_page", language="en", job_id="j2", invoice_id=str(uuid.uuid4())
            )
        )


# ---------------------------------------------------------------------------
# Job listing scoping
# ---------------------------------------------------------------------------


def test_job_list_scopes_to_cashier_counters(print_shop):
    ctx = print_shop
    with SessionLocal() as db:
        owner = _owner_principal(db, db.get(Shop, ctx["shop"].id))
        inv1 = _invoice(db, ctx, counter=ctx["c1"])
        inv2 = _invoice(db, ctx, counter=ctx["c2"])
        svc.enqueue_print(db, owner, inv1.id, ctx["printer"].id, None)
        svc.enqueue_print(db, owner, inv2.id, ctx["printer"].id, None)
        cashier = Principal(
            user_id=uuid.uuid4(),
            shop_id=ctx["shop"].id,
            email="c@x.dev",
            name="C",
            role_code="cashier",
            permissions=frozenset({"sales:read"}),
            assigned_counter_ids=frozenset({ctx["c1"].id}),
        )
        items, total = svc.list_jobs(db, cashier, None, None, 50, 0)
        assert total == 1
        assert items[0].counter_id == ctx["c1"].id

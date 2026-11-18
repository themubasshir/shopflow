"""Development seed data for ShopFlow.

Inserts a single demo shop, three counters, staff, categories, products,
customers, loyalty accounts, a few invoices and stock movements so every
Phase 1 page has realistic-looking, clearly-labelled demo data.

Run:  python -m seeds.seed   (from apps/api, PYTHONPATH=.)
Never run against production databases.
"""

from __future__ import annotations

import random
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

# Allow `python seed.py` directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "api"))

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.permissions import (
    CASHIER_PERMISSIONS,
    MANAGER_PERMISSIONS,
    OWNER_PERMISSIONS,
)
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models import (
    Category,
    Counter,
    Customer,
    Invoice,
    InvoiceItem,
    LoyaltyAccount,
    LoyaltyRule,
    LoyaltyTransaction,
    MedicineBatch,
    MedicineDetail,
    Payment,
    Product,
    ProductUnit,
    Role,
    Shop,
    StockMovement,
    Supplier,
    User,
    UserCounter,
)

rng = random.Random(42)
TODAY = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def main() -> None:
    with SessionLocal() as db:
        has_products = db.scalar(select(Product).limit(1)) is not None
        has_invoices = db.scalar(select(Invoice).limit(1)) is not None
        if has_products and has_invoices:
            print("database already seeded - idempotent, skipping")
            return
        if db.scalar(select(Shop).limit(1)) is None:
            seed(db)
            return
        if not has_invoices:
            seed_invoices(db)


def seed(db) -> None:
    shop = Shop(
        name_en="ShopFlow Pharmacy & Grocery",
        name_bn="শপফ্লো ফার্মেসি এবং গ্রোসারি",
        slug="shopflow-demo",
        address="Road 5, Dhanmondi, Dhaka 1205",
        phone="+8801712345678",
        currency="BDT",
        timezone="Asia/Dhaka",
        is_demo=True,
        is_active=True,
    )
    db.add(shop)
    db.flush()

    counters = [
        Counter(shop_id=shop.id, code="C1", name_en="Counter 1", name_bn="কাউন্টার ১", sort_order=1),
        Counter(shop_id=shop.id, code="C2", name_en="Counter 2", name_bn="কাউন্টার ২", sort_order=2),
        Counter(shop_id=shop.id, code="C3", name_en="Counter 3", name_bn="কাউন্টার ৩", sort_order=3),
    ]
    db.add_all(counters)

    owner_role = Role(
        shop_id=shop.id,
        code="owner",
        name_en="Shop Owner",
        name_bn="দোকান মালিক",
        permissions=OWNER_PERMISSIONS,
        is_system=True,
    )
    manager_role = Role(
        shop_id=shop.id,
        code="manager",
        name_en="Shop Manager",
        name_bn="দোকান ম্যানেজার",
        permissions=MANAGER_PERMISSIONS,
        is_system=True,
    )
    cashier_role = Role(
        shop_id=shop.id,
        code="cashier",
        name_en="Cashier",
        name_bn="ক্যাশিয়ার",
        permissions=CASHIER_PERMISSIONS,
        is_system=True,
    )
    db.add_all([owner_role, manager_role, cashier_role])
    db.flush()

    pw = hash_password("ShopFlow#Dev123")
    users = [
        User(
            shop_id=shop.id,
            role_id=owner_role.id,
            name="Jamal Hossain",
            email="owner@shopflow.dev",
            phone="+8801700000000",
            password_hash=pw,
            preferred_locale="en",
            is_active=True,
        ),
        User(
            shop_id=shop.id,
            role_id=manager_role.id,
            name="Rahim Uddin",
            email="manager@shopflow.dev",
            phone="+8801711111111",
            password_hash=pw,
            preferred_locale="en",
            is_active=True,
        ),
        User(
            shop_id=shop.id,
            role_id=cashier_role.id,
            name="Sadia Akter",
            email="cashier1@shopflow.dev",
            phone="+8801722222222",
            password_hash=pw,
            preferred_locale="bn",
            is_active=True,
        ),
        User(
            shop_id=shop.id,
            role_id=cashier_role.id,
            name="Karim Sheikh",
            email="cashier2@shopflow.dev",
            phone="+8801744444444",
            password_hash=pw,
            preferred_locale="en",
            is_active=True,
        ),
    ]
    db.add_all(users)
    db.flush()

    # Assign each cashier to a counter. Cashiers can only bill where assigned.
    # C1 -> cashier1, C2 -> cashier2, C3 left unassigned (any owner/manager can use).
    cashier1 = users[2]
    cashier2 = users[3]
    db.add_all(
        [
            UserCounter(shop_id=shop.id, user_id=cashier1.id, counter_id=counters[0].id),
            UserCounter(shop_id=shop.id, user_id=cashier2.id, counter_id=counters[1].id),
        ]
    )
    db.flush()

    grocery = Category(
        shop_id=shop.id,
        name_en="Grocery & Daily Needs",
        name_bn="মুদি ও দৈনন্দিন প্রয়োজন",
        slug="grocery",
        is_medicine=False,
        loyalty_eligible=True,
        sort_order=1,
    )
    medicine = Category(
        shop_id=shop.id,
        name_en="Medicines & Pharmacy",
        name_bn="ঔষধ ও ফার্মেসি",
        slug="medicine",
        is_medicine=True,
        loyalty_eligible=True,
        sort_order=2,
    )
    frozen = Category(
        shop_id=shop.id,
        name_en="Frozen & Dairy",
        name_bn="ফ্রোজেন ও দুগ্ধজাতীয়",
        slug="frozen",
        is_medicine=False,
        loyalty_eligible=True,
        sort_order=3,
    )
    non_eligible = Category(
        shop_id=shop.id,
        name_en="Lottery & Tobacco (no loyalty)",
        name_bn="লটারি ও তামাক",
        slug="excluded",
        is_medicine=False,
        loyalty_eligible=False,
        sort_order=4,
    )
    db.add_all([grocery, medicine, frozen, non_eligible])
    db.flush()

    def add_product(
        cat, sku, barcode, name_en, name_bn, aliases, unit, price, stock, low, med=None
    ):
        p = Product(
            shop_id=shop.id,
            category_id=cat.id,
            sku=sku,
            barcode=barcode,
            name_en=name_en,
            name_bn=name_bn,
            search_aliases=aliases,
            unit=unit,
            is_medicine=cat.is_medicine,
            is_active=True,
            stock_on_hand=Decimal(stock),
            low_stock_threshold=Decimal(low),
        )
        db.add(p)
        db.flush()
        pu = ProductUnit(
            product_id=p.id,
            name=f"per {unit}",
            name_bn=unit,
            conversion_factor=Decimal(1),
            selling_price=Decimal(price),
            is_base=True,
        )
        db.add(pu)
        if med:
            med_fields = {
                k: v for k, v in med.items() if k not in {"batch_number", "days_to_expiry"}
            }
            detail = MedicineDetail(
                product_id=p.id,
                source="seed",
                verified_at=None,
                **med_fields,
            )
            db.add(detail)
            batch = MedicineBatch(
                shop_id=shop.id,
                product_id=p.id,
                batch_number=med.get("batch_number", f"B{sku[-3:]}"),
                expiry_date=date.today() + timedelta(days=med.get("days_to_expiry", 365)),
                quantity_on_hand=Decimal(stock),
                purchase_cost=Decimal(price) * Decimal("0.82"),
                mrp=Decimal(price) * Decimal("1.08"),
            )
            db.add(batch)
        return p, pu

    add_product(
        grocery,
        "G-001",
        "8941001",
        "Nazirshail Rice 5kg",
        "নাজিরশাইল চাল ৫ কেজি",
        ["chal", "rice"],
        "kg",
        420,
        140,
        20,
    )
    add_product(
        grocery,
        "G-002",
        "8941002",
        "Soybean Oil 2L",
        "সয়াবিন তেল ২ লিটার",
        ["tel", "soybean oil"],
        "litre",
        390,
        80,
        15,
    )
    add_product(
        grocery,
        "G-003",
        "8941003",
        "Lentils 1kg",
        "মসুর ডাল ১ কেজি",
        ["dal", "mosur"],
        "kg",
        155,
        60,
        10,
    )
    add_product(
        grocery,
        "G-004",
        "8941004",
        "Milk Powder 500g",
        "গুঁড়ো দুধ ৫০০ গ্রাম",
        ["milk", "guro dudh"],
        "pack",
        540,
        45,
        12,
    )
    add_product(
        frozen,
        "F-001",
        "8941005",
        "Whole Chicken ~1.2kg",
        "সমগ্র মুরগি",
        ["murgi", "chicken"],
        "piece",
        320,
        24,
        8,
    )
    add_product(
        frozen, "F-002", "8941006", "Paratha 20pc", "পরোটা ২০টি", ["porota"], "pack", 280, 30, 10
    )

    add_product(
        medicine,
        "M-001",
        "8942001",
        "Napa 500mg",
        "নাপা ৫০০ মিলিগ্রাম",
        ["paracetamol", "napa"],
        "strip",
        20,
        220,
        50,
        med={
            "brand_name": "Napa",
            "generic_name": "Paracetamol",
            "manufacturer": "Beximco Pharmaceuticals",
            "strength": "500mg",
            "dosage_form": "tablet",
            "pack_size": "10's",
            "days_to_expiry": 42,
        },
    )
    add_product(
        medicine,
        "M-002",
        "8942002",
        "Fexo 120mg",
        "ফেক্সো ১২০ মিলিগ্রাম",
        ["fexofenadine", "fexo"],
        "strip",
        80,
        90,
        30,
        med={
            "brand_name": "Fexo",
            "generic_name": "Fexofenadine",
            "manufacturer": "Square Pharmaceuticals",
            "strength": "120mg",
            "dosage_form": "tablet",
            "pack_size": "10's",
            "days_to_expiry": 365,
        },
    )
    add_product(
        medicine,
        "M-003",
        "8942003",
        "Seclo 20mg",
        "সেক্লো ২০ মিলিগ্রাম",
        ["omeprazole", "seclo"],
        "strip",
        60,
        75,
        30,
        med={
            "brand_name": "Seclo",
            "generic_name": "Omeprazole",
            "manufacturer": "Square Pharmaceuticals",
            "strength": "20mg",
            "dosage_form": "capsule",
            "pack_size": "10's",
            "days_to_expiry": 300,
        },
    )
    add_product(
        medicine,
        "M-004",
        "8942004",
        "ORS Saline",
        "খাবার স্যালাইন",
        ["ors", "saline"],
        "sachet",
        6,
        400,
        100,
        med={
            "brand_name": "ORS",
            "generic_name": "Oral Rehydration Salts",
            "manufacturer": "SMC",
            "days_to_expiry": 540,
        },
    )
    add_product(
        medicine,
        "M-005",
        "8942005",
        "Ceevit 250mg",
        "সিভিট ২৫০ মিলিগ্রাম",
        ["vitamin c", "ceevit"],
        "strip",
        25,
        130,
        40,
        med={
            "brand_name": "Ceevit",
            "generic_name": "Ascorbic Acid",
            "manufacturer": "Square Pharmaceuticals",
            "days_to_expiry": 200,
        },
    )
    add_product(
        medicine,
        "M-006",
        "8942006",
        "Savlon Antiseptic 100ml",
        "স্যাভলন অ্যান্টিসেপ্টিক",
        ["antiseptic", "savlon"],
        "bottle",
        95,
        6,
        12,
        med={
            "brand_name": "Savlon",
            "generic_name": "Cetrimide + Chlorhexidine",
            "manufacturer": "ACI",
            "days_to_expiry": 25,
        },
    )
    add_product(
        non_eligible,
        "X-001",
        "8943001",
        "Lottery Ticket",
        "লটারি টিকিট",
        ["lottery"],
        "piece",
        20,
        200,
        0,
    )

    db.flush()

    supplier = Supplier(
        shop_id=shop.id,
        name="Dhaka Wholesale Mart",
        contact_person="Karim Bhai",
        phone="+8801833333333",
        is_medicine_supplier=False,
        is_active=True,
    )
    db.add(supplier)

    customers = [
        Customer(shop_id=shop.id, name="Walk-in Customer", phone=None, credit_limit=0),
        Customer(
            shop_id=shop.id,
            name="Nasrin Sultana",
            phone="+8801944444444",
            credit_limit=Decimal("500"),
        ),
        Customer(
            shop_id=shop.id,
            name="Abdul Karim",
            phone="+8801955555555",
            credit_limit=Decimal("1000"),
        ),
    ]
    db.add_all(customers)
    db.flush()

    accounts = []
    for cust, balance, earned in [
        (customers[1], 320, 620),
        (customers[2], 180, 180),
    ]:
        acct = LoyaltyAccount(
            customer_id=cust.id,
            shop_id=shop.id,
            points_balance=balance,
            lifetime_earned=earned,
            lifetime_redeemed=earned - balance,
        )
        db.add(acct)
        accounts.append(acct)
    db.add(
        LoyaltyRule(
            shop_id=shop.id,
            name="Default ShopFlow rule",
            points_per_100_bdt=1,
            min_redeem_balance=300,
            redeem_step_points=100,
            point_value_bdt=Decimal("1.00"),
            earn_on_eligible_category_only=True,
            is_active=True,
        )
    )
    db.flush()

    seed_invoices(db)


def seed_invoices(db) -> None:
    """Create a week of finalized invoices, payments and stock movements."""
    shop = db.scalar(select(Shop).order_by(Shop.created_at).limit(1))
    counters = (
        db.execute(select(Counter).where(Counter.shop_id == shop.id).order_by(Counter.sort_order))
        .scalars()
        .all()
    )
    users = (
        db.execute(select(User).where(User.shop_id == shop.id).order_by(User.created_at))
        .scalars()
        .all()
    )
    product_list = (
        db.execute(
            select(Product).options(selectinload(Product.units)).where(Product.shop_id == shop.id)
        )
        .scalars()
        .all()
    )
    customer_list = db.execute(select(Customer).where(Customer.shop_id == shop.id)).scalars().all()
    account_list = (
        db.execute(select(LoyaltyAccount).where(LoyaltyAccount.shop_id == shop.id)).scalars().all()
    )
    non_eligible_cat = db.scalar(select(Category).where(Category.slug == "excluded"))

    methods = ["cash", "bkash", "nagad"]
    invoice_no = 0
    for day_offset in range(7):
        day = TODAY - timedelta(days=day_offset)
        for counter_idx, counter in enumerate(counters):
            for _ in range(rng.randint(1, 3)):
                hour = rng.randint(9, 21)
                created = day.replace(hour=hour, minute=rng.randint(0, 59))
                eligible_pool = [p for p in product_list if p.category_id != non_eligible_cat.id]
                k = min(rng.randint(1, 4), len(eligible_pool))
                chosen = rng.sample(eligible_pool, k=k)
                items = []
                subtotal = Decimal(0)
                for prod in chosen:
                    qty = Decimal(rng.randint(1, 3))
                    price = rng.choice([u.selling_price for u in prod.units])
                    line_total = (qty * price).quantize(Decimal("0.01"))
                    items.append(
                        InvoiceItem(
                            product_id=prod.id,
                            product_unit_id=prod.units[0].id,
                            description=prod.name_en,
                            quantity=qty,
                            unit_price=price,
                            line_discount=Decimal(0),
                            tax_rate=prod.tax_rate,
                            line_total=line_total,
                            loyalty_eligible_amount=line_total,
                        )
                    )
                    subtotal += line_total
                discount = Decimal("0") if rng.random() < 0.7 else Decimal("20")
                discount = min(discount, (subtotal * Decimal("0.05")).quantize(Decimal("0.01")))
                total = (subtotal - discount).quantize(Decimal("0.01"))
                if total <= 0:
                    continue  # never seed a zero-value sale
                invoice_no += 1
                account_customers = [
                    c for c in customer_list if any(a.customer_id == c.id for a in account_list)
                ]
                customer = rng.choice([None, None, *account_customers])
                points = int(total // 100) if customer else 0
                inv = Invoice(
                    shop_id=shop.id,
                    counter_id=counter.id,
                    customer_id=customer.id if customer else None,
                    invoice_number=f"INV-{created.strftime('%y%m%d')}-{invoice_no:04d}",
                    status="finalized",
                    subtotal=subtotal,
                    discount_total=discount,
                    loyalty_discount=Decimal(0),
                    tax_total=Decimal(0),
                    total=total,
                    paid_total=total,
                    due_total=Decimal(0),
                    loyalty_points_earned=points,
                    loyalty_points_redeemed=0,
                    created_by=users[counter_idx % len(users)].id,
                    finalized_at=created,
                )
                inv.items = items
                inv.payments = [
                    Payment(
                        method=rng.choice(methods),
                        amount=total,
                        received_by=users[counter_idx % len(users)].id,
                        paid_at=created,
                    )
                ]
                db.add(inv)
                db.flush()
                for item in items:
                    db.add(
                        StockMovement(
                            shop_id=shop.id,
                            product_id=item.product_id,
                            counter_id=counter.id,
                            movement_type="sale",
                            quantity=-item.quantity,
                            reference_type="invoice",
                            reference_id=inv.id,
                            created_by=users[counter_idx % len(users)].id,
                        )
                    )
                if points:
                    acct = next(a for a in account_list if a.customer_id == customer.id)
                    acct.points_balance += points
                    acct.lifetime_earned += points
                    db.add(
                        LoyaltyTransaction(
                            account_id=acct.id,
                            invoice_id=inv.id,
                            transaction_type="earn",
                            points=points,
                            balance_after=acct.points_balance,
                            created_by=users[counter_idx % len(users)].id,
                        )
                    )

    db.commit()
    print(
        f"seeded: {invoice_no} invoices across 3 counters, "
        f"{len(product_list)} products, {len(account_list)} loyalty accounts"
    )


if __name__ == "__main__":
    main()

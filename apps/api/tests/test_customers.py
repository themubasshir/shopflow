import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError as PydanticError
from sqlalchemy import select

from app.core.config import Settings, settings
from app.db.session import SessionLocal
from app.main import app
from app.models import Customer, LoyaltyAccount, Shop
from app.services.customer_phone import normalize_mobile


@pytest.mark.parametrize(
    "raw", ["01712345678", "+880 (1712) 345-678", "008801712345678", "০১৭১২৩৪৫৬৭৮", "8801712345678"]
)
def test_normalize_equivalent_mobile_formats(raw):
    assert normalize_mobile(raw) == "+8801712345678"


@pytest.mark.parametrize(
    "raw", ["1234", "+911712345678", "01212345678", "01712345678 ext 3", "017123456789"]
)
def test_reject_invalid_mobile(raw):
    with pytest.raises(ValueError, match="Bangladeshi mobile"):
        normalize_mobile(raw)


@pytest.mark.parametrize("env", ["production", " PROD ", "staging"])
def test_demo_settings_fail_closed_in_deployed_environments(env):
    with pytest.raises(PydanticError, match="DEMO_MODE"):
        Settings(_env_file=None, environment=env, demo_mode=True, debug=False, secret_key="a" * 40)
    assert (
        Settings(
            _env_file=None, environment=env, demo_mode=False, debug=False, secret_key="a" * 40
        ).demo_mode
        is False
    )


def _local_phone() -> str:
    return f"016{uuid.uuid4().int % 100000000:08d}"


@pytest.fixture
async def client():
    transport = ASGITransport(app=app, client=("127.0.0.8", 12345))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def _login(client, email):
    response = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "ShopFlow#Dev123"}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.mark.anyio
async def test_customer_create_search_update_and_deactivate(client):
    auth = await _login(client, "manager@shopflow.dev")
    phone = _local_phone()
    bangla_digits = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")
    response = await client.post(
        "/api/v1/customers",
        headers=auth,
        json={
            "name": "  Nabila Alam  ",
            "name_bn": "নাবিলা আলম",
            "phone": phone.translate(bangla_digits),
            "credit_limit": "250.50",
        },
    )
    assert response.status_code == 201, response.text
    customer = response.json()
    assert customer["name"] == "Nabila Alam"
    assert customer["phone"] == "+880" + phone[1:]
    with SessionLocal() as db:
        account = db.scalar(
            select(LoyaltyAccount).where(LoyaltyAccount.customer_id == uuid.UUID(customer["id"]))
        )
        assert account.points_balance == 0
    for q in [phone, phone.translate(bangla_digits), "নাবিলা", "Nabila"]:
        result = await client.get("/api/v1/customers", params={"q": q}, headers=auth)
        assert result.status_code == 200, result.text
        assert customer["id"] in {row["id"] for row in result.json()["items"]}
    base = f"/api/v1/customers/{customer['id']}"
    response = await client.patch(
        base, headers=auth, json={"name_bn": "নাবিলা আক্তার", "is_active": False}
    )
    assert response.status_code == 200, response.text
    assert (await client.get(base, headers=auth)).json()["name_bn"] == "নাবিলা আক্তার"
    active = await client.get(
        "/api/v1/customers", headers=auth, params={"q": phone, "active": True}
    )
    inactive = await client.get(
        "/api/v1/customers", headers=auth, params={"q": phone, "active": False}
    )
    assert active.json()["items"] == []
    assert [row["id"] for row in inactive.json()["items"]] == [customer["id"]]


@pytest.mark.anyio
async def test_duplicate_mobile_on_create_and_edit(client):
    auth = await _login(client, "manager@shopflow.dev")
    phone = _local_phone()
    first = await client.post(
        "/api/v1/customers", headers=auth, json={"name": "First", "phone": phone}
    )
    original = await client.post(
        "/api/v1/customers", headers=auth, json={"name": "Second", "phone": _local_phone()}
    )
    assert first.status_code == original.status_code == 201
    response = await client.post(
        "/api/v1/customers", headers=auth, json={"name": "Duplicate", "phone": "00880" + phone[1:]}
    )
    assert response.status_code == 409
    assert response.json()["code"] == "duplicate_mobile"
    detail = f"/api/v1/customers/{original.json()['id']}"
    response = await client.patch(detail, headers=auth, json={"phone": "+880" + phone[1:]})
    assert response.status_code == 409
    assert (await client.get(detail, headers=auth)).json()["phone"] == original.json()["phone"]


@pytest.mark.anyio
async def test_customer_and_financial_permission_isolation(client, monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", True)
    manager = await _login(client, "manager@shopflow.dev")
    cashier = await _login(client, "cashier1@shopflow.dev")
    phone = _local_phone()
    created = await client.post(
        "/api/v1/customers",
        headers=manager,
        json={
            "name": "Hidden Credit",
            "phone": phone,
            "email": "example@shopflow.dev",
            "credit_limit": "450",
        },
    )
    assert created.status_code == 201
    base = f"/api/v1/customers/{created.json()['id']}"
    cashier_lookup = await client.get(base, headers=cashier)
    assert cashier_lookup.status_code == 200
    assert cashier_lookup.json()["credit_limit"] == "0"
    assert cashier_lookup.json()["email"] is None
    assert (await client.get(base + "/loyalty", headers=cashier)).status_code == 200
    for suffix in ["balance", "statement", "payments", "invoices", "loyalty/transactions"]:
        assert (await client.get(f"{base}/{suffix}", headers=cashier)).status_code == 403
        assert (await client.get(f"{base}/{suffix}")).status_code == 401
        assert (await client.get(f"{base}/{suffix}", headers=manager)).status_code == 200
    for auth, expected in [(cashier, 403), ({}, 401)]:
        assert (
            await client.patch(base, headers=auth, json={"is_active": False})
        ).status_code == expected
        assert (
            await client.post(
                "/api/v1/customers", headers=auth, json={"name": "Blocked", "phone": phone}
            )
        ).status_code == expected
        assert (
            await client.post(
                f"{base}/invoices/{uuid.uuid4()}/payments",
                headers={**auth, "Idempotency-Key": str(uuid.uuid4())},
                json={"amount": "1", "method": "cash"},
            )
        ).status_code == expected
    assert (await client.get("/api/v1/loyalty/accounts")).status_code == 401


@pytest.mark.anyio
async def test_customer_endpoints_look_up_records_only_within_the_callers_shop(client):
    manager = await _login(client, "manager@shopflow.dev")
    with SessionLocal() as db:
        remote = Shop(
            slug=str(uuid.uuid4()), name_en="Another shop", name_bn="অন্য দোকান", is_active=False
        )
        db.add(remote)
        db.flush()
        customer = Customer(
            shop_id=remote.id, name="Other tenant", phone=normalize_mobile(_local_phone())
        )
        db.add(customer)
        db.commit()
    base = f"/api/v1/customers/{customer.id}"
    assert (await client.get(base, headers=manager)).status_code == 404
    assert (await client.get(base + "/statement", headers=manager)).status_code == 404
    assert (await client.patch(base, headers=manager, json={"name": "Blocked"})).status_code == 404

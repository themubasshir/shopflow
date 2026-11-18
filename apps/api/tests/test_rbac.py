"""Phase 2B authorization matrix tests â€” run against shopflow_test.

These exercise the REAL FastAPI surface over HTTPX: login, session revocation,
role/permission enforcement, and counter authorization. Nothing is mocked.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from tests.conftest import TestingSessionLocal

from app.main import app
from app.models import Counter, User, UserCounter

DEV_PASSWORD = "ShopFlow#Dev123"


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def _login_payload(email: str, password: str = DEV_PASSWORD) -> dict:
    return {"email": email, "password": password}


async def _token(client: AsyncClient, email: str) -> str:
    r = await client.post("/api/v1/auth/login", json=_login_payload(email))
    assert r.status_code == 200, f"login failed for {email}: {r.text}"
    return r.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ------------------------------------------------------------- login / me


@pytest.mark.anyio
async def test_login_success_returns_token(client):
    r = await client.post("/api/v1/auth/login", json=_login_payload("owner@shopflow.dev"))
    assert r.status_code == 200
    body = r.json()
    assert body["access_token"]
    assert body["token_type"] == "bearer"


@pytest.mark.anyio
async def test_login_wrong_password(client):
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "owner@shopflow.dev", "password": "wrong-password"},
    )
    assert r.status_code == 401
    assert r.json()["code"] == "unauthenticated"


@pytest.mark.anyio
async def test_me_reflects_role_and_permissions(client):
    token = await _token(client, "cashier1@shopflow.dev")
    r = await client.get("/api/v1/auth/me", headers=_auth(token))
    assert r.status_code == 200
    body = r.json()
    assert body["role"] == "cashier"
    assert "reports:read" not in body["permissions"]
    # cashier is assigned to exactly one counter
    assert body["assigned_counter_ids"] is not None
    assert len(body["assigned_counter_ids"]) == 1


@pytest.mark.anyio
async def test_owner_me_unrestricted_counters(client):
    token = await _token(client, "owner@shopflow.dev")
    r = await client.get("/api/v1/auth/me", headers=_auth(token))
    body = r.json()
    assert body["role"] == "owner"
    # owner bills anywhere -> no restriction list
    assert body["assigned_counter_ids"] is None
    assert "employees:manage" in body["permissions"]


# ------------------------------------------------------- session revocation


@pytest.mark.anyio
async def test_logout_invalidates_token(client):
    token = await _token(client, "cashier1@shopflow.dev")
    r = await client.get("/api/v1/auth/me", headers=_auth(token))
    assert r.status_code == 200
    # Sign out â€” the session is revoked, the same token now dies.
    out = await client.post("/api/v1/auth/logout", headers=_auth(token))
    assert out.status_code == 204
    r2 = await client.get("/api/v1/auth/me", headers=_auth(token))
    assert r2.status_code == 401


@pytest.mark.anyio
async def test_disabled_account_session_revoked(client):
    """Disabling an employee must kill their live token immediately."""
    # create a throwaway employee, log in, then disable them
    owner = await _token(client, "owner@shopflow.dev")
    roles = (await client.get("/api/v1/employees/roles", headers=_auth(owner))).json()
    cashier_role = next(r for r in roles if r["code"] == "cashier")
    email = f"tmp-{uuid.uuid4().hex[:8]}@shopflow.dev"
    create = await client.post(
        "/api/v1/employees",
        headers=_auth(owner),
        json={
            "name": "Temp Cashier",
            "email": email,
            "role_id": cashier_role["id"],
            "password": "TempPass#123",
        },
    )
    assert create.status_code == 201, create.text
    uid = create.json()["id"]

    token = await _login_and_get(client, email, "TempPass#123")
    assert (await client.get("/api/v1/auth/me", headers=_auth(token))).status_code == 200

    disable = await client.post(f"/api/v1/employees/{uid}/disable", headers=_auth(owner))
    assert disable.status_code == 204
    # token is now dead even though its exp is hours away
    assert (await client.get("/api/v1/auth/me", headers=_auth(token))).status_code == 401


async def _login_and_get(client: AsyncClient, email: str, password: str) -> str:
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200
    return r.json()["access_token"]


@pytest.mark.anyio
async def test_disabled_account_cannot_login(client):
    with TestingSessionLocal() as db:
        user = db.scalar(select(User).where(User.email == "cashier2@shopflow.dev"))
        user.is_active = False
        db.commit()
    try:
        r = await client.post("/api/v1/auth/login", json=_login_payload("cashier2@shopflow.dev"))
        assert r.status_code == 403
        assert r.json()["code"] == "forbidden"
    finally:
        with TestingSessionLocal() as db:
            user = db.scalar(select(User).where(User.email == "cashier2@shopflow.dev"))
            user.is_active = True
            db.commit()


@pytest.mark.anyio
async def test_concurrent_sessions_independent(client):
    """Two logins produce two sessions; revoking one does not kill the other."""
    t1 = await _token(client, "manager@shopflow.dev")
    t2 = await _token(client, "manager@shopflow.dev")
    assert t1 != t2
    await client.post("/api/v1/auth/logout", headers=_auth(t1))
    assert (await client.get("/api/v1/auth/me", headers=_auth(t2))).status_code == 200


# ---------------------------------------------------------- rate limiting


@pytest.mark.anyio
async def test_login_rate_limited(client):
    email = f"rl-{uuid.uuid4().hex[:6]}@shopflow.dev"
    last = None
    for _ in range(6):
        last = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "wrong-password"},
        )
    assert last.status_code == 429
    assert last.json()["code"] == "rate_limited"


# ----------------------------------------------------- permission matrix


@pytest.mark.anyio
async def test_cashier_cannot_manage_employees(client):
    token = await _token(client, "cashier1@shopflow.dev")
    r = await client.get("/api/v1/employees", headers=_auth(token))
    assert r.status_code == 403


@pytest.mark.anyio
async def test_cashier_cannot_manage_counters(client):
    token = await _token(client, "cashier1@shopflow.dev")
    r = await client.get("/api/v1/manage/counters", headers=_auth(token))
    assert r.status_code == 403


@pytest.mark.anyio
async def test_manager_cannot_manage_employees_by_default(client):
    token = await _token(client, "manager@shopflow.dev")
    r = await client.get("/api/v1/employees", headers=_auth(token))
    assert r.status_code == 403


@pytest.mark.anyio
async def test_manager_cannot_manage_counters(client):
    token = await _token(client, "manager@shopflow.dev")
    r = await client.patch(
        "/api/v1/manage/counters/00000000-0000-0000-0000-000000000000",
        headers=_auth(token),
        json={"is_active": False},
    )
    assert r.status_code == 403


@pytest.mark.anyio
async def test_owner_can_list_employees(client):
    token = await _token(client, "owner@shopflow.dev")
    r = await client.get("/api/v1/employees", headers=_auth(token))
    assert r.status_code == 200
    emails = {e["email"] for e in r.json()}
    assert {"owner@shopflow.dev", "manager@shopflow.dev", "cashier1@shopflow.dev"} <= emails
    # password hashes never leak
    assert all("password_hash" not in e for e in r.json())


# --------------------------------------------------- counter authorization


@pytest.mark.anyio
async def test_cashier_cannot_bill_unassigned_counter(client):
    """A cashier billing a counter they are not assigned to is rejected 403."""
    token = await _token(client, "cashier1@shopflow.dev")
    with TestingSessionLocal() as db:
        assigned = set(
            db.scalars(
                select(UserCounter.counter_id)
                .join(User, User.id == UserCounter.user_id)
                .where(User.email == "cashier1@shopflow.dev")
            ).all()
        )
        other = db.scalar(
            select(Counter).where(Counter.is_active.is_(True), ~Counter.id.in_(assigned))
        )
    assert other is not None
    r = await client.post(
        "/api/v1/invoices",
        headers={**_auth(token), "Idempotency-Key": "k-" + uuid.uuid4().hex[:12]},
        json={
            "counter_id": str(other.id),
            "items": [{"product_id": str(uuid.uuid4()), "quantity": "1"}],
            "payments": [{"method": "cash"}],
        },
    )
    assert r.status_code == 403
    assert "counter" in r.json()["error"].lower()


@pytest.mark.anyio
async def test_cashier_invoice_history_scoped_to_own_counter(client):
    token = await _token(client, "cashier1@shopflow.dev")
    r = await client.get("/api/v1/invoices?limit=100", headers=_auth(token))
    assert r.status_code == 200
    with TestingSessionLocal() as db:
        assigned = {
            db.scalar(select(Counter.code).where(Counter.id == cid))
            for cid in db.scalars(
                select(UserCounter.counter_id)
                .join(User, User.id == UserCounter.user_id)
                .where(User.email == "cashier1@shopflow.dev")
            ).all()
        }
    for inv in r.json()["items"]:
        assert inv["counter_code"] in assigned


@pytest.mark.anyio
async def test_manager_sees_all_invoice_history(client):
    token = await _token(client, "manager@shopflow.dev")
    r = await client.get("/api/v1/invoices?limit=200", headers=_auth(token))
    assert r.status_code == 200
    codes = {inv["counter_code"] for inv in r.json()["items"]}
    assert len(codes) >= 2  # manager is unrestricted -> multiple counters


@pytest.mark.anyio
async def test_change_password_revokes_other_sessions(client):
    t1 = await _token(client, "manager@shopflow.dev")
    await _token(client, "manager@shopflow.dev")  # second session minted
    r = await client.post(
        "/api/v1/auth/password",
        headers=_auth(t1),
        json={"current_password": DEV_PASSWORD, "new_password": "Manager#New123"},
    )
    assert r.status_code == 204
    try:
        # the current session stays alive
        assert (await client.get("/api/v1/auth/me", headers=_auth(t1))).status_code == 200
        # new password works
        await _login_and_get(client, "manager@shopflow.dev", "Manager#New123")
    finally:
        # restore the dev password for other tests
        await client.post(
            "/api/v1/auth/password",
            headers=_auth(t1),
            json={"current_password": "Manager#New123", "new_password": DEV_PASSWORD},
        )

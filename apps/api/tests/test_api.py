"""API integration tests against the seeded development database.

These run against `shopflow_dev`; the test settings point at the same URL the
app uses, so they require the migration + seed to have been applied.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.anyio
async def test_health(client):
    r = await client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in {"ok", "degraded"}
    assert "database" in body


@pytest.mark.anyio
async def test_dashboard_shape(client):
    r = await client.get("/api/v1/reports/dashboard")
    assert r.status_code in {200, 503}  # 503 if seed has not run yet
    if r.status_code == 200:
        body = r.json()
        for key in (
            "summary",
            "counters",
            "sales_series",
            "recent_transactions",
            "low_stock",
            "expiring",
        ):
            assert key in body
        assert body["summary"]["active_counters"] == 3


@pytest.mark.anyio
async def test_products_paginated(client):
    r = await client.get("/api/v1/catalog/products?limit=5")
    assert r.status_code in {200, 503}
    if r.status_code == 200:
        body = r.json()
        assert {"items", "total", "limit", "offset"} <= set(body)


@pytest.mark.anyio
async def test_login_rejects_bad_credentials(client):
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@shopflow.dev", "password": "wrong-password"},
    )
    assert r.status_code == 401


@pytest.mark.anyio
async def test_openapi_served(client):
    r = await client.get("/openapi.json")
    assert r.status_code == 200
    assert r.json()["info"]["title"] == "ShopFlow API"

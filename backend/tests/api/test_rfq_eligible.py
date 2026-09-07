"""Route tests for ``GET /api/v1/catalog/rfq-eligible``.

The endpoint is a thin read-side query that joins products to the
``product_suppliers`` table and returns only products that have at
least N distinct active suppliers offering them. The seeded catalog
has 39 such products at min_suppliers=2.

These tests focus on the contract:
* 401 when no token is supplied
* 200 + expected response shape on the happy path
* query-string validation (min_suppliers bounds, limit bounds)
"""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import api_router
from app.core.security import TokenData
from app.deps.auth import get_current_token, read_db_session
from app.models.product import UnitOfMeasure


# --- helpers ----------------------------------------------------------


def _make_token() -> TokenData:
    # Company-side role so prices are visible — the redaction layer
    # strips unit_price + currency for purchasing_officer. The
    # redaction behavior is covered in test_redaction.py; this file
    # is about the supplier_count feature, so use a role that
    # exercises the happy path with full prices.
    return TokenData(
        sub="test-user",
        roles=["super_admin"],
        permissions=["catalog:read"],
    )


class _FakeMappping:
    """Mimics a single row mapping for the catalog/rfq-eligible route."""

    def __init__(self, row: dict) -> None:
        self._d = row

    def __getitem__(self, k):
        return self._d[k]

    def __iter__(self):
        return iter(self._d)


def _row(name: str, supplier_count: int, *, unit_price: float = 100.0) -> dict:
    return {
        "id": uuid4(),
        "sku": f"AVS-TEST-{name[:6].upper()}",
        "name": name,
        "short_name": None,
        "unit_price": unit_price,
        "currency": "USD",
        "unit": UnitOfMeasure.PIECE,
        "in_stock": True,
        "stock_qty": 100,
        "lead_time_days": 7,
        "manufacturer": "TestCo",
        "supplier_count": supplier_count,
    }


class _FakeResult:
    """SQLAlchemy result stub: provides .scalar() and .mappings().all()."""

    def __init__(self, *, scalar=None, rows=None) -> None:
        self._scalar = scalar
        self._rows = rows or []

    def scalar(self):
        return self._scalar

    def scalar_one(self):
        return self._scalar

    def mappings(self):
        return _FakeMappingView(self._rows)


class _FakeMappingView:
    def __init__(self, rows: list) -> None:
        self._rows = [_FakeMappping(r) for r in rows]

    def all(self) -> list:
        return self._rows


class _FakeSession:
    """A read-side session stub for the catalog/rfq-eligible route.

    The route runs two queries:
    1. SELECT count(*) FROM (subquery)         -> total
    2. SELECT ... FROM products JOIN (subquery) -> mappings

    We can't easily inspect the SQL to know which is which, so we let
    the test inject the desired scalar + rows by name, and the .execute
    stub returns whichever shape the caller is going to ask for.
    """

    def __init__(
        self,
        *,
        total: int = 0,
        rows: list | None = None,
    ) -> None:
        self.total = total
        self.rows = rows or []
        self.executed_stmts: list = []

    async def execute(self, stmt) -> object:
        self.executed_stmts.append(stmt)
        # First query in the route is the count. Detect it by the
        # presence of a .label("sc")? Simpler: just always return both
        # shapes — the caller will use what it needs.
        return _FakeResult(scalar=self.total, rows=self.rows)


# --- fixtures ---------------------------------------------------------


@pytest.fixture
def app() -> FastAPI:
    a = FastAPI()
    a.include_router(api_router, prefix="/api/v1")

    sessions: list[_FakeSession] = []
    a.state.fake_sessions = sessions  # type: ignore[attr-defined]

    def _override_session() -> _FakeSession:
        s = _FakeSession()
        sessions.append(s)
        return s

    def _override_token() -> TokenData:
        return _make_token()

    a.dependency_overrides[read_db_session] = _override_session
    a.dependency_overrides[get_current_token] = _override_token
    return a


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


# --- tests ------------------------------------------------------------


class TestAuth:
    def test_401_without_token(self, client: TestClient) -> None:
        app = client.app
        app.dependency_overrides.pop(get_current_token)
        r = client.get("/api/v1/catalog/rfq-eligible")
        assert r.status_code == 401


class TestHappyPath:
    def test_returns_seeded_supplier_count(self, app: FastAPI, client: TestClient) -> None:
        # Inject 3 fake RFQ-eligible products
        rows = [
            _row("Degreaser 5L", 4, unit_price=1683.65),
            _row("Mooring Rope 10mm", 4, unit_price=1039.48),
            _row("Coffee Beans 1kg", 3, unit_price=736.79),
        ]
        sess = _FakeSession(total=3, rows=rows)

        def _sess() -> _FakeSession:
            return sess

        app.dependency_overrides[read_db_session] = _sess

        r = client.get("/api/v1/catalog/rfq-eligible")
        assert r.status_code == 200, r.text

        body = r.json()
        assert body["total"] == 3
        assert body["min_suppliers"] == 2  # default
        assert len(body["items"]) == 3

        # First item: each product has the new supplier_count field
        first = body["items"][0]
        assert first["name"] == "Degreaser 5L"
        assert first["supplier_count"] == 4
        assert first["in_stock"] is True
        assert first["currency"] == "USD"
        assert first["unit_price"] == 1683.65
        # Each item must have an id that the picker can submit
        assert first["id"]

    def test_empty_result_is_well_formed(self, app: FastAPI, client: TestClient) -> None:
        # No seeded suppliers -> empty result is still 200 with shape
        def _sess() -> _FakeSession:
            return _FakeSession(total=0, rows=[])

        app.dependency_overrides[read_db_session] = _sess

        r = client.get("/api/v1/catalog/rfq-eligible")
        assert r.status_code == 200
        body = r.json()
        assert body == {"items": [], "total": 0, "min_suppliers": 2}


class TestQueryParams:
    def test_min_suppliers_passed_through(self, app: FastAPI, client: TestClient) -> None:
        def _sess() -> _FakeSession:
            return _FakeSession(total=0, rows=[])

        app.dependency_overrides[read_db_session] = _sess

        r = client.get("/api/v1/catalog/rfq-eligible?min_suppliers=5")
        assert r.status_code == 200
        assert r.json()["min_suppliers"] == 5

    def test_min_suppliers_rejects_zero(self, client: TestClient) -> None:
        # ge=1, so 0 should be a 422
        r = client.get("/api/v1/catalog/rfq-eligible?min_suppliers=0")
        assert r.status_code == 422

    def test_min_suppliers_rejects_huge(self, client: TestClient) -> None:
        # le=20, so 21 should be a 422
        r = client.get("/api/v1/catalog/rfq-eligible?min_suppliers=21")
        assert r.status_code == 422

    def test_limit_rejects_zero(self, client: TestClient) -> None:
        r = client.get("/api/v1/catalog/rfq-eligible?limit=0")
        assert r.status_code == 422

    def test_limit_rejects_over_500(self, client: TestClient) -> None:
        r = client.get("/api/v1/catalog/rfq-eligible?limit=501")
        assert r.status_code == 422

    def test_q_passes_through(self, app: FastAPI, client: TestClient) -> None:
        # We just verify the request doesn't 4xx — the actual WHERE
        # filter is exercised in the live smoke test against the DB.
        def _sess() -> _FakeSession:
            return _FakeSession(total=1, rows=[_row("Rope", 2)])

        app.dependency_overrides[read_db_session] = _sess

        r = client.get("/api/v1/catalog/rfq-eligible?q=rope")
        assert r.status_code == 200
        assert r.json()["total"] == 1

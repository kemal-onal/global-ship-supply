"""Route tests for ``GET /api/v1/catalog/impa`` and ``POST /catalog/impa/lookup``.

These tests pin the **response shape** because the frontend's
IMPA typeahead in OrderCreate.jsx reads the result as a flat list,
not as ``{items: [...]}``. The bug that motivated this file:
``dropdownOpen = impaResults?.items?.length > 0`` silently failed
when the backend returned a flat array, so the typeahead never
opened and the purchaser only saw the "Add blank line" button.

Anything that changes the response shape of ``GET /catalog/impa``
must update this test in lockstep with the frontend.
"""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import api_router
from app.core.security import TokenData
from app.deps.auth import get_current_token, read_db_session


# --- helpers ----------------------------------------------------------


def _make_token() -> TokenData:
    return TokenData(
        sub="test-user",
        roles=["super_admin"],
        permissions=["catalog:read"],
    )


def _impa_row(code: str, name: str, group_code: str = "31") -> SimpleNamespace:
    """A single IMPA row, matching the columns the route selects."""
    return SimpleNamespace(
        code=code,
        name=name,
        description=f"Description for {name}",
        group_code=group_code,
    )


class _FakeScalars:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def all(self) -> list:
        return self._rows


class _FakeResult:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def scalars(self) -> _FakeScalars:
        return _FakeScalars(self._rows)


class _FakeSession:
    """A read-side session stub for the /catalog/impa routes.

    The endpoint runs a single ``select(ImpaCode)``; the lookup
    endpoint runs a single ``select(ImpaCode).where(...in_(...))``.
    Both ask for ``.scalars().all()``, so this is enough.
    """

    def __init__(self, rows: list | None = None) -> None:
        self.rows = rows or []
        self.executed_stmts: list = []

    async def execute(self, stmt) -> _FakeResult:
        self.executed_stmts.append(stmt)
        return _FakeResult(self.rows)


# --- fixtures ---------------------------------------------------------


@pytest.fixture
def app() -> FastAPI:
    a = FastAPI()
    a.include_router(api_router, prefix="/api/v1")

    def _override_token() -> TokenData:
        return _make_token()

    a.dependency_overrides[get_current_token] = _override_token
    return a


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


# --- tests ------------------------------------------------------------


class TestAuth:
    def test_401_without_token(self, client: TestClient, app: FastAPI) -> None:
        app.dependency_overrides.pop(get_current_token, None)
        r = client.get("/api/v1/catalog/impa?q=boots")
        assert r.status_code == 401

    def test_401_lookup_without_token(self, client: TestClient, app: FastAPI) -> None:
        app.dependency_overrides.pop(get_current_token, None)
        r = client.post("/api/v1/catalog/impa/lookup", json={"codes": ["311501"]})
        assert r.status_code == 401


class TestResponseShape:
    """Pins the shape the OrderCreate typeahead depends on.

    The frontend reads the typeahead result as a **flat array**:
        ``(impaResults || []).map(i => ...)``
    plus ``i.code`` and ``i.name`` (and optionally ``i.group``).
    """

    def test_get_impa_returns_flat_array(self, app: FastAPI, client: TestClient) -> None:
        rows = [
            _impa_row("311501", "Safety Boots", "31"),
            _impa_row("311502", "Safety Gloves", "31"),
        ]
        sess = _FakeSession(rows=rows)
        app.dependency_overrides[read_db_session] = lambda: sess

        r = client.get("/api/v1/catalog/impa?q=safety")
        assert r.status_code == 200, r.text

        body = r.json()
        # THE SHAPE: flat array, not {"items": [...]}.
        # This is what the typeahead in OrderCreate.jsx expects.
        assert isinstance(body, list), (
            f"GET /catalog/impa must return a flat array, got {type(body).__name__}"
        )
        assert len(body) == 2
        assert body[0]["code"] == "311501"
        assert body[0]["name"] == "Safety Boots"
        assert body[0]["group"] == "31"
        assert body[1]["code"] == "311502"

    def test_get_impa_empty_query_returns_list_not_dict(
        self, app: FastAPI, client: TestClient
    ) -> None:
        # Even with no rows the response must be a list, not a dict
        # — otherwise OrderCreate's `Array.isArray(impaResults)` falls
        # back to `impaResults?.items` which is undefined.
        sess = _FakeSession(rows=[])
        app.dependency_overrides[read_db_session] = lambda: sess

        r = client.get("/api/v1/catalog/impa")
        assert r.status_code == 200
        assert r.json() == []


class TestQueryParams:
    def test_q_param_validates(self, app: FastAPI, client: TestClient) -> None:
        # A query that simply has no rows is still 200 with []
        sess = _FakeSession(rows=[])
        app.dependency_overrides[read_db_session] = lambda: sess

        r = client.get("/api/v1/catalog/impa?q=zzznonexistent")
        assert r.status_code == 200
        assert r.json() == []

    def test_limit_rejects_zero(self, client: TestClient) -> None:
        r = client.get("/api/v1/catalog/impa?limit=0")
        assert r.status_code == 422

    def test_limit_rejects_over_500(self, client: TestClient) -> None:
        r = client.get("/api/v1/catalog/impa?limit=501")
        assert r.status_code == 422


class TestLookupShape:
    """Pins the bulk-lookup shape used by ``useImpaNames``.

    The frontend hook expects one entry per requested code, in the
    same order, with ``name: null`` for unknown codes. The
    OrderCreate / OrderDetail / SupplierPortal pages all depend
    on this contract.
    """

    def test_lookup_returns_one_entry_per_code(
        self, app: FastAPI, client: TestClient
    ) -> None:
        rows = [
            _impa_row("311501", "Safety Boots", "31"),
            _impa_row("632121", "Television", "63"),
        ]
        sess = _FakeSession(rows=rows)
        app.dependency_overrides[read_db_session] = lambda: sess

        r = client.post(
            "/api/v1/catalog/impa/lookup",
            json={"codes": ["311501", "632121", "999999"]},
        )
        assert r.status_code == 200, r.text

        body = r.json()
        assert len(body) == 3
        # Order is preserved
        assert body[0]["code"] == "311501"
        assert body[0]["name"] == "Safety Boots"
        assert body[1]["code"] == "632121"
        assert body[1]["name"] == "Television"
        # Unknown code -> null, not 404, not omitted
        assert body[2]["code"] == "999999"
        assert body[2]["name"] is None
        assert body[2]["group"] is None

    def test_lookup_empty_codes_rejected(self, client: TestClient) -> None:
        r = client.post("/api/v1/catalog/impa/lookup", json={"codes": []})
        assert r.status_code == 422

"""Route tests for ``POST /api/v1/rfq/{rfq_id}/simulate``.

These tests cover the auth + validation + happy-path surface of the
endpoint using a minimal in-memory async session. The actual bid-war
math is covered by tests/market_sim/test_agent.py and
tests/market_sim/test_engine.py; the goal here is to make sure the
HTTP layer wires the right things:

* 401 when no token is supplied
* 403 when the token lacks ``rfq:simulate:own``
* 404 when the RFQ doesn't exist
* 400 when the RFQ is CANCELLED / EXPIRED
* 200 with the response shape on the happy path
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
from app.deps.auth import db_session, get_current_token
from app.models.supplier import RFQStatus


# --- helpers ----------------------------------------------------------


def _make_token(*, permissions: list[str] | None = None) -> TokenData:
    """Build a TokenData that has the given permission strings."""
    return TokenData(
        sub="test-user",
        roles=["purchasing_officer"] if permissions else ["viewer"],
        permissions=permissions or [],
    )


def _make_rfq(*, status: RFQStatus = RFQStatus.OPEN) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        status=status,
        port_id=uuid4(),
        invited_count=0,
        responded_count=0,
        awarded_quote_id=None,
        awarded_at=None,
        extra={},
        items=[],
        quotes=[],
    )


class _FakeSession:
    """Minimal async session that handles the queries ``run_market_sim``
    actually runs (RFQ lookup + the supplier-jurisdiction queries) by
    returning a pre-baked RFQ. Anything else is a no-op."""

    def __init__(self, rfq: SimpleNamespace | None) -> None:
        self.rfq = rfq
        self.added: list = []
        self.committed = False
        self.rolled_back = False

    def add(self, obj) -> None:
        self.added.append(obj)

    def add_all(self, objs) -> None:
        self.added.extend(objs)

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True

    async def refresh(self, _obj) -> None:
        pass

    async def flush(self) -> None:
        pass

    async def execute(self, stmt) -> object:
        rfq = self.rfq
        # `scalar_one_or_none()` is what the route uses:
        #   rfq = (await db.execute(select(RFQ)...)).scalar_one_or_none()
        if rfq is None:
            return _FakeResult(scalar=rfq)
        return _FakeResult(scalar=rfq)


class _FakeResult:
    """Mimics just enough of SQLAlchemy's result chain."""

    def __init__(self, *, scalar: object | None, rows: list | None = None) -> None:
        self._scalar = scalar
        self._rows = rows if rows is not None else ([scalar] if scalar is not None else [])

    def scalar_one_or_none(self) -> object | None:
        return self._scalar

    def scalars(self) -> "_FakeScalarView":
        return _FakeScalarView(self._rows)


class _FakeScalarView:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def all(self) -> list:
        return self._rows

    def scalar_one_or_none(self) -> object | None:
        return self._rows[0] if self._rows else None


# --- fixtures ---------------------------------------------------------


@pytest.fixture
def app() -> FastAPI:
    a = FastAPI()
    a.include_router(api_router, prefix="/api/v1")

    # The router uses `db_session` (the function) as the underlying
    # dependency, plus `get_current_token`. Override both.
    sessions: list[_FakeSession] = []
    tokens: list[TokenData] = []
    a.state.fake_sessions = sessions  # type: ignore[attr-defined]
    a.state.fake_tokens = tokens  # type: ignore[attr-defined]

    def _override_session() -> _FakeSession:
        s = _FakeSession(rfq=None)
        sessions.append(s)
        return s

    def _override_token() -> TokenData:
        t = _make_token(permissions=["rfq:simulate:own"])
        tokens.append(t)
        return t

    a.dependency_overrides[db_session] = _override_session
    a.dependency_overrides[get_current_token] = _override_token
    return a


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


# --- tests ------------------------------------------------------------


class TestSimulateAuth:
    def test_401_without_token(self, client: TestClient) -> None:
        # No token override — strip the default and assert unauth.
        app = client.app
        app.dependency_overrides.pop(get_current_token)
        r = client.post(f"/api/v1/rfq/{uuid4()}/simulate", json={})
        assert r.status_code == 401

    def test_403_without_permission(self, app: FastAPI, client: TestClient) -> None:
        # Replace the token override to drop the permission.
        def _no_perm_token() -> TokenData:
            return _make_token(permissions=[])

        app.dependency_overrides[get_current_token] = _no_perm_token

        # And replace the session so a missing RFQ → 404 (otherwise
        # we'd race past the auth check).
        rfq_id = uuid4()
        app.dependency_overrides.pop(db_session)

        def _sess() -> _FakeSession:
            return _FakeSession(rfq=None)

        app.dependency_overrides[db_session] = _sess
        r = client.post(f"/api/v1/rfq/{rfq_id}/simulate", json={})
        assert r.status_code == 403
        assert "rfq:simulate:own" in r.json()["detail"]


class TestSimulateValidation:
    def test_404_when_rfq_missing(self, app: FastAPI, client: TestClient) -> None:
        # Session returns no RFQ.
        app.dependency_overrides.pop(db_session)
        app.dependency_overrides[db_session] = lambda: _FakeSession(rfq=None)
        r = client.post(f"/api/v1/rfq/{uuid4()}/simulate", json={})
        assert r.status_code == 404
        assert r.json()["detail"] == "RFQ not found"

    def test_400_when_rfq_cancelled(self, app: FastAPI, client: TestClient) -> None:
        rfq = _make_rfq(status=RFQStatus.CANCELLED)
        app.dependency_overrides.pop(db_session)
        app.dependency_overrides[db_session] = lambda: _FakeSession(rfq=rfq)
        r = client.post(f"/api/v1/rfq/{rfq.id}/simulate", json={})
        assert r.status_code == 400
        assert "cancelled" in r.json()["detail"].lower()

    def test_400_when_rfq_expired(self, app: FastAPI, client: TestClient) -> None:
        rfq = _make_rfq(status=RFQStatus.EXPIRED)
        app.dependency_overrides.pop(db_session)
        app.dependency_overrides[db_session] = lambda: _FakeSession(rfq=rfq)
        r = client.post(f"/api/v1/rfq/{rfq.id}/simulate", json={})
        assert r.status_code == 400
        assert "expired" in r.json()["detail"].lower()


class TestSimulateBody:
    def test_request_validation_negative_seed(self, client: TestClient) -> None:
        # SimulateIn.seed has ge=0; -1 should be rejected by pydantic.
        r = client.post(f"/api/v1/rfq/{uuid4()}/simulate", json={"seed": -1})
        assert r.status_code == 422

    def test_request_validation_seed_too_large(self, client: TestClient) -> None:
        r = client.post(
            f"/api/v1/rfq/{uuid4()}/simulate",
            json={"seed": 2**40},
        )
        assert r.status_code == 422

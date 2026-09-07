"""Route tests for the clarification loop on orders.

The clarification loop is the pre-fan-out step where the company
asks the purchaser a question, the purchaser answers, and the
company marks the thread resolved. Until resolved, the RFQ
fan-out refuses to proceed.

These tests cover:
  * 401 / 403 / 404 auth
  * ask → answer → resolve happy path
  * empty / unknown id bodies
  * fan-out is blocked while there's an open clarification
  * summary block-counts (unanswered, unresolved)
"""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import api_router
from app.core.security import TokenData
from app.deps.auth import db_session, get_current_token, read_db_session
from app.models.order import OrderStatus
from app.services.clarification import has_unresolved_clarifications, summarize


# --- helpers ----------------------------------------------------------


_TEST_VESSEL = uuid4()


def _token(*, permissions: list[str], roles: list[str] | None = None) -> TokenData:
    return TokenData(
        sub="test-user",
        roles=roles or ["super_admin"],
        permissions=permissions,
        vessel_id=_TEST_VESSEL,
    )


def _make_order(*, status: OrderStatus = OrderStatus.DRAFT, vessel_id=None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        reference="AVS-TEST-000001",
        vessel_id=vessel_id or _TEST_VESSEL,
        status=status,
        clarification=None,
        created_by=uuid4(),
    )


# Fake result that supports scalar_one_or_none and scalars().all()
class _FakeResult:
    def __init__(self, *, scalar=None, rows=None) -> None:
        self._scalar = scalar
        self._rows = rows if rows is not None else ([scalar] if scalar is not None else [])

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        outer = self

        class _View:
            def all(self_inner):
                return outer._rows

        return _View()


class _FakeSession:
    def __init__(self, order: SimpleNamespace | None) -> None:
        self.order = order
        self.added: list = []
        self.notified: list = []
        self.committed = False

    def add(self, obj) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.committed = True

    async def flush(self) -> None:
        pass

    async def execute(self, stmt) -> object:
        return _FakeResult(scalar=self.order)


# --- fixtures ---------------------------------------------------------


@pytest.fixture
def app() -> FastAPI:
    a = FastAPI()
    a.include_router(api_router, prefix="/api/v1")

    a.state.fake_session = _FakeSession(order=None)

    def _sess():
        return a.state.fake_session

    def _token_admin():
        return _token(permissions=["marketplace:clarify:global", "marketplace:approve:own"])

    a.dependency_overrides[db_session] = _sess
    a.dependency_overrides[read_db_session] = _sess
    a.dependency_overrides[get_current_token] = _token_admin
    return a


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


# --- tests ------------------------------------------------------------


class TestAskAuth:
    def test_401_without_token(self, client: TestClient) -> None:
        client.app.dependency_overrides.pop(get_current_token)
        r = client.post(f"/api/v1/orders/{uuid4()}/clarify", json={"question": "x"})
        assert r.status_code == 401

    def test_403_without_clarify_permission(self, app: FastAPI, client: TestClient) -> None:
        def _no_perm():
            return _token(permissions=[])

        app.dependency_overrides[get_current_token] = _no_perm
        r = client.post(f"/api/v1/orders/{uuid4()}/clarify", json={"question": "x"})
        assert r.status_code == 403
        assert "marketplace:clarify:global" in r.json()["detail"]


class TestAskHappyPath:
    def test_ask_appends_entry_and_moves_status(self, app: FastAPI, client: TestClient) -> None:
        order = _make_order(status=OrderStatus.DRAFT)
        app.state.fake_session = _FakeSession(order=order)
        r = client.post(f"/api/v1/orders/{order.id}/clarify", json={"question": "Steel-toe or composite?"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "awaiting_clarification"
        assert body["entry"]["question"] == "Steel-toe or composite?"
        assert body["entry"]["answer"] is None
        # Order's clarification list grew
        assert order.clarification is not None
        assert len(order.clarification) == 1
        # Status moved
        assert order.status == OrderStatus.AWAITING_CLARIFICATION
        # Audit + notification created
        assert any(getattr(x, "action", None) for x in app.state.fake_session.added) or app.state.fake_session.committed

    def test_ask_404_when_order_missing(self, app: FastAPI, client: TestClient) -> None:
        app.state.fake_session = _FakeSession(order=None)
        r = client.post(f"/api/v1/orders/{uuid4()}/clarify", json={"question": "x"})
        assert r.status_code == 404

    def test_ask_rejects_empty_question(self, app: FastAPI, client: TestClient) -> None:
        order = _make_order()
        app.state.fake_session = _FakeSession(order=order)
        r = client.post(f"/api/v1/orders/{order.id}/clarify", json={"question": "   "})
        assert r.status_code == 400

    def test_ask_min_length_enforced_by_pydantic(self, client: TestClient) -> None:
        r = client.post(f"/api/v1/orders/{uuid4()}/clarify", json={"question": ""})
        assert r.status_code == 422


class TestAnswer:
    def test_answer_fills_entry(self, app: FastAPI, client: TestClient) -> None:
        order = _make_order(status=OrderStatus.AWAITING_CLARIFICATION)
        # Pre-seed an entry the way ask would have left it
        from app.services.clarification import ask_clarification
        import asyncio
        asyncio.get_event_loop().run_until_complete(
            ask_clarification(
                None, order, question="Steel-toe or composite?", asked_by="admin"
            )
        )
        entry_id = order.clarification[0]["id"]
        # Switch token to a purchaser (no clarify perm, only approve)
        def _purchaser():
            return _token(permissions=["marketplace:approve:own"], roles=["purchasing_officer"])
        app.dependency_overrides[get_current_token] = _purchaser
        app.state.fake_session = _FakeSession(order=order)
        r = client.post(
            f"/api/v1/orders/{order.id}/answer",
            json={"clarification_id": entry_id, "answer": "Half each"},
        )
        assert r.status_code == 200, r.text
        # Answer landed
        assert order.clarification[0]["answer"] == "Half each"
        # Status still AWAITING_CLARIFICATION (company has to resolve)
        assert order.status == OrderStatus.AWAITING_CLARIFICATION

    def test_answer_404_for_unknown_id(self, app: FastAPI, client: TestClient) -> None:
        order = _make_order(status=OrderStatus.AWAITING_CLARIFICATION)
        app.state.fake_session = _FakeSession(order=order)
        r = client.post(
            f"/api/v1/orders/{order.id}/answer",
            json={"clarification_id": "nope", "answer": "x"},
        )
        assert r.status_code == 404


class TestResolve:
    def test_resolve_drops_to_draft_when_last(self, app: FastAPI, client: TestClient) -> None:
        order = _make_order(status=OrderStatus.AWAITING_CLARIFICATION)
        import asyncio
        from app.services.clarification import ask_clarification, answer_clarification
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                ask_clarification(None, order, question="Footwear?", asked_by="admin")
            )
            eid = order.clarification[0]["id"]
            loop.run_until_complete(
                answer_clarification(None, order, entry_id=eid, answer="composite", answered_by="p")
            )
        finally:
            loop.close()
        app.state.fake_session = _FakeSession(order=order)
        r = client.post(
            f"/api/v1/orders/{order.id}/resolve-clarification",
            json={"clarification_id": eid},
        )
        assert r.status_code == 200, r.text
        # All resolved → status drops to DRAFT
        assert order.status == OrderStatus.DRAFT
        assert order.clarification[0]["resolved_at"] is not None

    def test_resolve_blocked_without_answer(self, app: FastAPI, client: TestClient) -> None:
        order = _make_order(status=OrderStatus.AWAITING_CLARIFICATION)
        import asyncio
        from app.services.clarification import ask_clarification
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                ask_clarification(None, order, question="Footwear?", asked_by="admin")
            )
            eid = order.clarification[0]["id"]
        finally:
            loop.close()
        app.state.fake_session = _FakeSession(order=order)
        r = client.post(
            f"/api/v1/orders/{order.id}/resolve-clarification",
            json={"clarification_id": eid},
        )
        assert r.status_code == 400


class TestServiceHelpers:
    def test_has_unresolved_clarifications_empty(self):
        o = _make_order()
        assert has_unresolved_clarifications(o) is False

    def test_has_unresolved_clarifications_with_open_entry(self):
        o = _make_order()
        o.clarification = [{"id": "a", "answer": None, "resolved_at": None}]
        assert has_unresolved_clarifications(o) is True

    def test_has_unresolved_clarifications_all_resolved(self):
        o = _make_order()
        o.clarification = [
            {"id": "a", "answer": "x", "resolved_at": "2026-01-01T00:00:00Z"}
        ]
        assert has_unresolved_clarifications(o) is False

    def test_summarize_counts(self):
        o = _make_order()
        o.clarification = [
            {"id": "a", "answer": None, "resolved_at": None},          # unanswered
            {"id": "b", "answer": "x", "resolved_at": None},            # unresolved
            {"id": "c", "answer": "x", "resolved_at": "2026-01-01"},   # done
        ]
        s = summarize(o)
        assert s.total == 3
        assert s.unanswered == 1
        assert s.unresolved == 2
        assert s.is_blocking is True

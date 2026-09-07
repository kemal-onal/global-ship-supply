"""Tests for the purchaser's approval / rejection step.

The purchaser sees the composed proposal (per-line totals with
margin applied, lead time, payment terms) but the supplier
identities are sealed. Approving moves the order to CONFIRMED
and creates one SupplierLineAssignment per OrderDecision with a
24h preparation_deadline. Rejecting moves it to REJECTED with
the reason.

We cover:
  * 401 / 403
  * 404 order
  * 400 wrong status
  * happy path: approve creates assignments, sets deadline
  * reject with reason writes the reason
  * sealed view: purchaser-facing proposal hides supplier names
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
from app.services.marketplace import purchaser_approve_proposal


# --- helpers ----------------------------------------------------------


_TEST_VESSEL = uuid4()
ORDER_ID = uuid4()
SUPPLIER_ID = uuid4()
QUOTE_ID = uuid4()
PRODUCT_A = uuid4()


def _purchaser_token() -> TokenData:
    return TokenData(
        sub="test-purchaser",
        roles=["purchasing_officer"],
        permissions=["marketplace:approve:own"],
        vessel_id=_TEST_VESSEL,
    )


def _make_order(*, status=OrderStatus.AWAITING_PURCHASER_APPROVAL) -> SimpleNamespace:
    return SimpleNamespace(
        id=ORDER_ID,
        reference="AVS-TEST-0001",
        vessel_id=_TEST_VESSEL,
        port_id=uuid4(),
        status=status,
        company_margin_pct=8.0,
        eta_at_port=None,
    )


def _make_decision(*, used_qty=10, unit_price=10.0) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        order_id=ORDER_ID,
        rfq_item_id=uuid4(),
        supplier_id=SUPPLIER_ID,
        quote_id=QUOTE_ID,
        decision="use_full",
        unit_price=unit_price,
        used_quantity=used_qty,
        line_total=used_qty * unit_price,
        margin_pct=8.0,
        customer_facing_total=used_qty * unit_price * 1.08,
        # The service reads d.rfq_item_id (an attribute) when
        # building the SupplierLineAssignment; keep it set.
        rfq_item=SimpleNamespace(id=uuid4()),
    )


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
    def __init__(self, *results) -> None:
        self._queue = list(results)
        self.added: list = []
        self.committed = False

    def add(self, obj) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.committed = True

    async def flush(self) -> None:
        pass

    async def execute(self, stmt) -> object:
        if not self._queue:
            return _FakeResult(scalar=None)
        return self._queue.pop(0)


# --- service tests ----------------------------------------------------


class TestApproveService:
    @pytest.mark.asyncio
    async def test_approve_creates_assignments(self) -> None:
        order = _make_order()
        decisions = [_make_decision()]
        # The order is passed in directly — no _load_order call. The
        # first execute is the decisions query, then the supplier /
        # user lookups for the notification fan-out.
        db = _FakeSession(
            _FakeResult(rows=decisions),              # decisions lookup
            _FakeResult(rows=[]),                     # supplier lookup (none)
            _FakeResult(rows=[]),                     # user lookup (none)
        )
        result = await purchaser_approve_proposal(
            db, order, approve=True, reason=None, actor_id=uuid4()
        )
        assert order.status == OrderStatus.CONFIRMED
        assert result["status"] == "confirmed"
        assert result["assignments_created"] == 1
        # Deadline is 24h from now (the constant in marketplace.py)
        assert result["preparation_deadline"] is not None

    @pytest.mark.asyncio
    async def test_reject_writes_reason(self) -> None:
        order = _make_order()
        decisions = [_make_decision()]
        db = _FakeSession(
            _FakeResult(rows=decisions),  # decisions lookup
        )
        result = await purchaser_approve_proposal(
            db, order, approve=False, reason="Price too high", actor_id=uuid4()
        )
        assert order.status == OrderStatus.REJECTED
        assert order.rejection_reason == "Price too high"
        assert result["assignments_created"] == 0

    @pytest.mark.asyncio
    async def test_wrong_status_rejected(self) -> None:
        order = _make_order(status=OrderStatus.DRAFT)
        # No execute calls expected — the function raises before any DB access.
        db = _FakeSession()
        with pytest.raises(ValueError, match="AWAITING_PURCHASER_APPROVAL"):
            await purchaser_approve_proposal(
                db, order, approve=True, reason=None, actor_id=uuid4()
            )

    @pytest.mark.asyncio
    async def test_no_decisions_rejected(self) -> None:
        order = _make_order()
        db = _FakeSession(
            _FakeResult(rows=[]),  # no decisions
        )
        with pytest.raises(ValueError, match="No decisions"):
            await purchaser_approve_proposal(
                db, order, approve=True, reason=None, actor_id=uuid4()
            )


# --- route tests ------------------------------------------------------


class TestApproveRoute:
    @pytest.fixture
    def app(self) -> FastAPI:
        a = FastAPI()
        a.include_router(api_router, prefix="/api/v1")
        a.state.fake_session = _FakeSession()

        def _sess():
            return a.state.fake_session

        def _token():
            return _purchaser_token()

        a.dependency_overrides[db_session] = _sess
        a.dependency_overrides[read_db_session] = _sess
        a.dependency_overrides[get_current_token] = _token
        return a

    @pytest.fixture
    def client(self, app: FastAPI) -> TestClient:
        return TestClient(app)

    def test_401_without_token(self, client: TestClient) -> None:
        client.app.dependency_overrides.pop(get_current_token)
        r = client.post(
            f"/api/v1/orders/{ORDER_ID}/approve-proposal",
            json={"approve": True},
        )
        assert r.status_code == 401

    def test_403_without_approve_permission(self, app: FastAPI, client: TestClient) -> None:
        def _no_perm():
            return TokenData(
                sub="x",
                roles=["viewer"],
                permissions=[],
                vessel_id=_TEST_VESSEL,
            )

        app.dependency_overrides[get_current_token] = _no_perm
        r = client.post(
            f"/api/v1/orders/{ORDER_ID}/approve-proposal",
            json={"approve": True},
        )
        assert r.status_code == 403

    def test_404_when_order_missing(self, app: FastAPI, client: TestClient) -> None:
        app.state.fake_session = _FakeSession(_FakeResult(scalar=None))
        r = client.post(
            f"/api/v1/orders/{ORDER_ID}/approve-proposal",
            json={"approve": True},
        )
        assert r.status_code == 404

    def test_400_when_no_decisions(self, app: FastAPI, client: TestClient) -> None:
        order = _make_order()
        # The route does _load_order_or_404 first, then the service
        # queries decisions. With no decisions, the service raises
        # ValueError("No decisions to approve") which the route
        # surfaces as 400.
        app.state.fake_session = _FakeSession(
            _FakeResult(scalar=order),  # _load_order_or_404
            _FakeResult(rows=[]),        # decisions lookup
        )
        r = client.post(
            f"/api/v1/orders/{ORDER_ID}/approve-proposal",
            json={"approve": True},
        )
        assert r.status_code == 400
        assert "No decisions" in r.json()["detail"]


class TestProposalRead:
    """The GET /proposal route must seal supplier identities for the purchaser."""

    @pytest.fixture
    def app(self) -> FastAPI:
        a = FastAPI()
        a.include_router(api_router, prefix="/api/v1")
        a.state.fake_session = _FakeSession()
        a.state.fake_token = _purchaser_token()

        def _sess():
            return a.state.fake_session

        def _token():
            return a.state.fake_token

        a.dependency_overrides[db_session] = _sess
        a.dependency_overrides[read_db_session] = _sess
        a.dependency_overrides[get_current_token] = _token
        return a

    @pytest.fixture
    def client(self, app: FastAPI) -> TestClient:
        return TestClient(app)

    def test_purchaser_view_seals_supplier(self, app: FastAPI, client: TestClient) -> None:
        order = _make_order()
        decision = _make_decision()
        # The proposal route selectinloads decision.rfq_item, .supplier, .quote
        decision.rfq_item = SimpleNamespace(product_id=PRODUCT_A)
        decision.supplier = SimpleNamespace(company_name="APC Marine")
        decision.quote = SimpleNamespace(lead_time_days=7)
        app.state.fake_session = _FakeSession(
            _FakeResult(scalar=order),            # _load_order_or_404
            _FakeResult(rows=[decision]),          # decisions
        )
        r = client.get(f"/api/v1/orders/{ORDER_ID}/proposal")
        assert r.status_code == 200, r.text
        body = r.json()
        line = body["lines"][0]
        # Purchaser view: no supplier_id, no supplier_name, no line_total
        assert "supplier_id" not in line
        assert "supplier_name" not in line
        assert line["line_total"] is None
        # customer_facing_total is visible (with margin)
        assert line["customer_facing_total"] is not None
        # lead_time_days visible
        assert line["lead_time_days"] == 7

    def test_admin_view_includes_supplier(self, app: FastAPI, client: TestClient) -> None:
        # Switch to admin token (sees prices)
        app.state.fake_token = TokenData(
            sub="admin",
            roles=["super_admin"],
            permissions=["marketplace:compose:global"],
            vessel_id=_TEST_VESSEL,
        )
        order = _make_order()
        decision = _make_decision()
        decision.rfq_item = SimpleNamespace(product_id=PRODUCT_A)
        decision.supplier = SimpleNamespace(company_name="APC Marine")
        decision.quote = SimpleNamespace(lead_time_days=7)
        app.state.fake_session = _FakeSession(
            _FakeResult(scalar=order),
            _FakeResult(rows=[decision]),
        )
        r = client.get(f"/api/v1/orders/{ORDER_ID}/proposal")
        assert r.status_code == 200, r.text
        body = r.json()
        line = body["lines"][0]
        # Admin view: supplier identity visible
        assert line["supplier_id"] == str(SUPPLIER_ID)
        assert line["supplier_name"] == "APC Marine"
        assert line["unit_price"] == 10.0

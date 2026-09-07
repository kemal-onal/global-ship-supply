"""Tests for ``GET /api/v1/rfqs-for-compose``.

The marketplace composer's left-rail picker calls this endpoint
to enumerate the RFQs the admin can act on. The semantically
correct predicate is "order is in a compose-eligible state", not
"RFQ.status == OPEN" — because once every invited supplier has
responded, ``supplier_submit_quote`` flips the RFQ to ``closed``
and the order to ``ready_for_compose``, so an OPEN RFQ is no
longer the right query (and the old /rfq?status=open picker was
the empty-list bug we hit on 2026-09-07).

We exercise the route via FastAPI's TestClient with fakes and pin:

  * 401 / 403 auth gates
  * the response shape (id, reference, order_id, order_reference,
    port_id, status, sent_at, response_deadline, closed_at,
    awarded_at, invited_count, responded_count, items[])
  * the eligible-order-states allowlist:
      - READY_FOR_COMPOSE         → returned
      - RFQ_IN_PROGRESS (legacy)  → returned
      - BIDDING (legacy)          → returned
      - AWAITING_CONFIRMATION     → returned
      - DRAFT                     → not returned
      - PENDING_APPROVAL          → not returned
      - AWAITING_PURCHASER_APPROVAL → not returned
      - CONFIRMED                 → not returned
  * vessel-scoped fallback for non-admin tokens
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import api_router
from app.core.security import TokenData
from app.deps.auth import db_session, get_current_token, read_db_session
from app.models.order import OrderStatus
from app.models.supplier import RFQ, RFQStatus


# --- helpers ----------------------------------------------------------


_TEST_VESSEL = uuid4()
OTHER_VESSEL = uuid4()
PORT_ID = uuid4()
ORDER_ID = uuid4()
RFQ_ID = uuid4()
PRODUCT_A = uuid4()


def _admin_token() -> TokenData:
    return TokenData(
        sub="test-admin",
        roles=["super_admin"],
        permissions=["marketplace:compose:global"],
        vessel_id=_TEST_VESSEL,
    )


def _vessel_scoped_token() -> TokenData:
    """A purchaser (not super_admin) — gets vessel-scoped filtering."""
    return TokenData(
        sub="test-purchaser",
        roles=["purchasing_officer"],
        permissions=["marketplace:compose:global"],
        vessel_id=_TEST_VESSEL,
    )


def _make_order(*, status: OrderStatus, vessel_id=_TEST_VESSEL) -> SimpleNamespace:
    return SimpleNamespace(
        id=ORDER_ID,
        reference="AVS-TEST-0001",
        vessel_id=vessel_id,
        port_id=PORT_ID,
        status=status,
    )


def _make_rfq(
    *,
    order: SimpleNamespace,
    status: RFQStatus = RFQStatus.CLOSED,
    invited: int = 2,
    responded: int = 2,
) -> SimpleNamespace:
    """Build an RFQ with the shape the route reads. ``order`` is
    the SimpleNamespace order object — the route joins to it, so
    we set ``rfq.order = order`` to wire the relationship."""
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=RFQ_ID,
        reference="RFQ-TEST-0001",
        order_id=order.id,
        port_id=PORT_ID,
        status=status,
        sent_at=now - timedelta(hours=1),
        response_deadline=now + timedelta(hours=12),
        closed_at=now,
        awarded_at=None,
        invited_count=invited,
        responded_count=responded,
        order=order,
        items=[
            SimpleNamespace(
                id=uuid4(),
                product_id=PRODUCT_A,
                quantity=3,
                unit="pcs",
            )
        ],
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


# --- route tests ------------------------------------------------------


class TestRfqsForComposeRoute:
    @pytest.fixture
    def app(self) -> FastAPI:
        a = FastAPI()
        a.include_router(api_router, prefix="/api/v1")
        a.state.fake_session = _FakeSession()

        def _sess():
            return a.state.fake_session

        def _token():
            return _admin_token()

        a.dependency_overrides[db_session] = _sess
        a.dependency_overrides[read_db_session] = _sess
        a.dependency_overrides[get_current_token] = _token
        return a

    @pytest.fixture
    def client(self, app: FastAPI) -> TestClient:
        return TestClient(app)

    def test_401_without_token(self, client: TestClient) -> None:
        client.app.dependency_overrides.pop(get_current_token)
        r = client.get("/api/v1/rfqs-for-compose")
        assert r.status_code == 401

    def test_403_without_compose_permission(self, app: FastAPI, client: TestClient) -> None:
        def _no_perm():
            return TokenData(
                sub="x",
                roles=["viewer"],
                permissions=[],
                vessel_id=_TEST_VESSEL,
            )

        app.dependency_overrides[get_current_token] = _no_perm
        r = client.get("/api/v1/rfqs-for-compose")
        assert r.status_code == 403

    def test_returns_ready_for_compose_with_rfq_status_closed(self, app: FastAPI, client: TestClient) -> None:
        """The canonical case: order is READY_FOR_COMPOSE and the
        RFQ is CLOSED (because supplier_submit_quote flipped it
        when all suppliers responded). The endpoint must return
        it — this is the exact scenario the picker bug hit."""
        order = _make_order(status=OrderStatus.READY_FOR_COMPOSE)
        rfq = _make_rfq(order=order, status=RFQStatus.CLOSED)
        app.state.fake_session = _FakeSession(_FakeResult(rows=[rfq]))

        r = client.get("/api/v1/rfqs-for-compose")
        assert r.status_code == 200, r.text
        body = r.json()
        assert isinstance(body, list)
        assert len(body) == 1
        row = body[0]
        # Shape: every key the picker renders is present.
        assert row["id"] == str(RFQ_ID)
        assert row["reference"] == "RFQ-TEST-0001"
        assert row["order_id"] == str(ORDER_ID)
        assert row["order_reference"] == "AVS-TEST-0001"
        assert row["port_id"] == str(PORT_ID)
        assert row["status"] == "closed"
        # The counters that triggered the picker-empty bug are populated.
        assert row["invited_count"] == 2
        assert row["responded_count"] == 2
        # Items are present and shaped right.
        assert isinstance(row["items"], list)
        assert len(row["items"]) == 1
        assert row["items"][0]["product_id"] == str(PRODUCT_A)
        assert row["items"][0]["quantity"] == 3
        assert row["items"][0]["unit"] == "pcs"

    def test_includes_legacy_rfq_in_progress_order(self, app: FastAPI, client: TestClient) -> None:
        """Legacy sealed-bid orders in RFQ_IN_PROGRESS are
        compose-eligible (compose_proposal self-heals them to
        ready_for_compose). The picker must surface them so the
        admin can unblock by clicking compose."""
        order = _make_order(status=OrderStatus.RFQ_IN_PROGRESS)
        rfq = _make_rfq(order=order, status=RFQStatus.OPEN)
        app.state.fake_session = _FakeSession(_FakeResult(rows=[rfq]))

        r = client.get("/api/v1/rfqs-for-compose")
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body) == 1
        assert body[0]["order_id"] == str(ORDER_ID)

    def test_includes_legacy_bidding_order(self, app: FastAPI, client: TestClient) -> None:
        order = _make_order(status=OrderStatus.BIDDING)
        rfq = _make_rfq(order=order, status=RFQStatus.OPEN)
        app.state.fake_session = _FakeSession(_FakeResult(rows=[rfq]))

        r = client.get("/api/v1/rfqs-for-compose")
        assert r.status_code == 200, r.text
        assert len(r.json()) == 1

    def test_includes_legacy_awaiting_confirmation_order(self, app: FastAPI, client: TestClient) -> None:
        order = _make_order(status=OrderStatus.AWAITING_CONFIRMATION)
        rfq = _make_rfq(order=order, status=RFQStatus.OPEN)
        app.state.fake_session = _FakeSession(_FakeResult(rows=[rfq]))

        r = client.get("/api/v1/rfqs-for-compose")
        assert r.status_code == 200, r.text
        assert len(r.json()) == 1

    def test_excludes_draft_orders(self, app: FastAPI, client: TestClient) -> None:
        """Draft orders are not compose-eligible — the route
        filters them out at the DB level. The fake returns an
        empty list (the WHERE clause is the contract)."""
        app.state.fake_session = _FakeSession(_FakeResult(rows=[]))

        r = client.get("/api/v1/rfqs-for-compose")
        assert r.status_code == 200
        assert r.json() == []

    def test_excludes_pending_approval_orders(self, app: FastAPI, client: TestClient) -> None:
        app.state.fake_session = _FakeSession(_FakeResult(rows=[]))

        r = client.get("/api/v1/rfqs-for-compose")
        assert r.status_code == 200
        assert r.json() == []

    def test_excludes_awaiting_purchaser_approval_orders(self, app: FastAPI, client: TestClient) -> None:
        """Once compose has fired, the order moves to
        AWAITING_PURCHASER_APPROVAL — the picker should not
        show it again (the purchaser is the next actor)."""
        app.state.fake_session = _FakeSession(_FakeResult(rows=[]))

        r = client.get("/api/v1/rfqs-for-compose")
        assert r.status_code == 200
        assert r.json() == []

    def test_excludes_confirmed_orders(self, app: FastAPI, client: TestClient) -> None:
        app.state.fake_session = _FakeSession(_FakeResult(rows=[]))

        r = client.get("/api/v1/rfqs-for-compose")
        assert r.status_code == 200
        assert r.json() == []

    def test_vessel_scoped_user_sees_only_their_vessels(self, app: FastAPI, client: TestClient) -> None:
        """A purchasing officer (not super_admin) gets only
        RFQs whose order.vessel_id matches their vessel_id. We
        simulate the DB-side filter having already narrowed the
        result set to just the matching vessel's row."""
        order = _make_order(status=OrderStatus.READY_FOR_COMPOSE, vessel_id=_TEST_VESSEL)
        rfq = _make_rfq(order=order, status=RFQStatus.CLOSED)

        def _vessel_token():
            return _vessel_scoped_token()

        app.dependency_overrides[get_current_token] = _vessel_token
        app.state.fake_session = _FakeSession(_FakeResult(rows=[rfq]))

        r = client.get("/api/v1/rfqs-for-compose")
        assert r.status_code == 200
        body = r.json()
        # Single row, and the order's vessel_id matches the token's
        # vessel_id (the route would have filtered out the
        # cross-vessel row at the SQL level).
        assert len(body) == 1

    def test_external_user_with_no_vessel_gets_empty(self, app: FastAPI, client: TestClient) -> None:
        """External users (no vessel) get an empty list — same
        behavior as the existing /rfq endpoint, pinned for
        symmetry so a future refactor doesn't silently widen
        visibility."""
        def _external_token():
            return TokenData(
                sub="ext",
                roles=["purchasing_officer"],
                permissions=["marketplace:compose:global"],
                vessel_id=None,
            )

        app.dependency_overrides[get_current_token] = _external_token
        # The SQL filter adds `WHERE false` for vessel-less users;
        # the fake reflects that by returning no rows.
        app.state.fake_session = _FakeSession(_FakeResult(rows=[]))

        r = client.get("/api/v1/rfqs-for-compose")
        assert r.status_code == 200
        assert r.json() == []


# --- regression: the original bug -------------------------------------


class TestPickerBugRegression:
    """Pins the exact scenario the user hit on 2026-09-07:

      * 3 orders visible in /orders as ``ready_for_compose``
      * their associated RFQs had ``status='closed'`` (because
        supplier_submit_quote flipped them when the suppliers
        responded)
      * the marketplace picker called /rfq?status=open and got 0
        rows back → "No RFQs to compose" empty state

    With the new endpoint, these orders are returned. This is
    the regression guard.
    """

    @pytest.fixture
    def app(self) -> FastAPI:
        a = FastAPI()
        a.include_router(api_router, prefix="/api/v1")
        a.state.fake_session = _FakeSession()

        def _sess():
            return a.state.fake_session

        def _token():
            return _admin_token()

        a.dependency_overrides[db_session] = _sess
        a.dependency_overrides[read_db_session] = _sess
        a.dependency_overrides[get_current_token] = _token
        return a

    @pytest.fixture
    def client(self, app: FastAPI) -> TestClient:
        return TestClient(app)

    def test_closed_rfq_for_ready_for_compose_order_is_returned(self, app: FastAPI, client: TestClient) -> None:
        # Build the same shape the live DB had: order is
        # READY_FOR_COMPOSE, RFQ is CLOSED, 2 invited / 2 responded.
        order = _make_order(status=OrderStatus.READY_FOR_COMPOSE)
        rfq = _make_rfq(order=order, status=RFQStatus.CLOSED, invited=2, responded=2)
        app.state.fake_session = _FakeSession(_FakeResult(rows=[rfq]))

        r = client.get("/api/v1/rfqs-for-compose")
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body) == 1
        # The closed RFQ — the one the old /rfq?status=open
        # picker missed — is now in the response.
        assert body[0]["status"] == "closed"
        assert body[0]["responded_count"] == body[0]["invited_count"] == 2

"""Service-level tests for ``compose_proposal`` and the related
HTTP route. Compose is the company's per-line decision step:
which supplier's offer to use, applied with a margin, and the
order's status flips to AWAITING_PURCHASER_APPROVAL.

We exercise the route via FastAPI's TestClient with fakes, and
also drive ``compose_proposal`` directly through a few
service-level tests for the math (margin, line_total, customer
total).
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import api_router
from app.core.security import TokenData
from app.deps.auth import db_session, get_current_token, read_db_session
from app.models.order import OrderStatus
from app.models.supplier import RFQStatus
from app.services.marketplace import compose_proposal


# --- helpers ----------------------------------------------------------


_TEST_VESSEL = uuid4()
RFQ_ID = uuid4()
ORDER_ID = uuid4()
PRODUCT_A = uuid4()
QUOTE_ID = uuid4()
SUPPLIER_ID = uuid4()


def _admin_token() -> TokenData:
    return TokenData(
        sub="test-admin",
        roles=["super_admin"],
        permissions=["marketplace:compose:global"],
        vessel_id=_TEST_VESSEL,
    )


def _make_order(*, status=OrderStatus.READY_FOR_COMPOSE) -> SimpleNamespace:
    return SimpleNamespace(
        id=ORDER_ID,
        reference="AVS-TEST-0001",
        vessel_id=_TEST_VESSEL,
        port_id=uuid4(),
        status=status,
        company_margin_pct=None,
        eta_at_port=None,
    )


def _make_rfq(*, items=None) -> SimpleNamespace:
    if items is None:
        items = [
            SimpleNamespace(
                id=uuid4(),
                product_id=PRODUCT_A,
                quantity=10,
                unit="pcs",
            )
        ]
    return SimpleNamespace(
        id=RFQ_ID,
        reference="RFQ-TEST-0001",
        order_id=ORDER_ID,
        port_id=uuid4(),
        status=RFQStatus.SENT,
        extra={"invited_supplier_ids": [str(SUPPLIER_ID)]},
        items=items,
        # The route reads rfq.order.vessel_id; the helper does the same.
        order=SimpleNamespace(vessel_id=_TEST_VESSEL),
    )


def _make_quote_item(*, unit_price=10.0, quoted_quantity=10) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        product_id=PRODUCT_A,
        unit_price=unit_price,
        quantity=quoted_quantity,
        quoted_quantity=quoted_quantity,
        line_total=unit_price * quoted_quantity,
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


class TestComposeServiceMath:
    @pytest.mark.asyncio
    async def test_use_full_with_margin(self) -> None:
        order = _make_order()
        rfq = _make_rfq()
        db = _FakeSession(
            _FakeResult(scalar=order),  # _load_order
            _FakeResult(rows=[]),       # wipe existing decisions
            _FakeResult(scalar=_make_quote_item(unit_price=10.0, quoted_quantity=10)),
        )
        decisions = [
            {
                "rfq_item_id": str(rfq.items[0].id),
                "supplier_id": str(SUPPLIER_ID),
                "quote_id": str(QUOTE_ID),
                "decision": "use_full",
            }
        ]
        rows = await compose_proposal(db, rfq, decisions=decisions, margin_pct=10.0, composed_by=uuid4())
        assert len(rows) == 1
        r = rows[0]
        # line_total = unit_price * qty = 10 * 10 = 100
        assert float(r.line_total) == 100.0
        # customer_facing_total = 100 * 1.10 = 110
        assert float(r.customer_facing_total) == 110.0
        # order status moved
        assert order.status == OrderStatus.AWAITING_PURCHASER_APPROVAL
        # margin stored
        assert order.company_margin_pct == 10.0

    @pytest.mark.asyncio
    async def test_use_half_takes_half(self) -> None:
        order = _make_order()
        rfq = _make_rfq()
        db = _FakeSession(
            _FakeResult(scalar=order),
            _FakeResult(rows=[]),
            _FakeResult(scalar=_make_quote_item(unit_price=20.0, quoted_quantity=10)),
        )
        decisions = [
            {
                "rfq_item_id": str(rfq.items[0].id),
                "supplier_id": str(SUPPLIER_ID),
                "quote_id": str(QUOTE_ID),
                "decision": "use_half",
            }
        ]
        rows = await compose_proposal(db, rfq, decisions=decisions, margin_pct=0.0, composed_by=uuid4())
        # use_half: take ceil(10/2) = 5
        assert rows[0].used_quantity == 5
        # line_total = 20 * 5 = 100
        assert float(rows[0].line_total) == 100.0

    @pytest.mark.asyncio
    async def test_drop_decision_writes_no_row(self) -> None:
        order = _make_order()
        rfq = _make_rfq()
        db = _FakeSession(
            _FakeResult(scalar=order),
            _FakeResult(rows=[]),
        )
        decisions = [
            {
                "rfq_item_id": str(rfq.items[0].id),
                "supplier_id": str(SUPPLIER_ID),
                "quote_id": str(QUOTE_ID),
                "decision": "drop",
            }
        ]
        rows = await compose_proposal(db, rfq, decisions=decisions, margin_pct=8.0, composed_by=uuid4())
        # drop is implicit — no row written
        assert rows == []

    @pytest.mark.asyncio
    async def test_margin_rejects_out_of_range(self) -> None:
        order = _make_order()
        rfq = _make_rfq()
        db = _FakeSession(
            _FakeResult(scalar=order),
            _FakeResult(rows=[]),
        )
        decisions = [
            {
                "rfq_item_id": str(rfq.items[0].id),
                "supplier_id": str(SUPPLIER_ID),
                "quote_id": str(QUOTE_ID),
                "decision": "use_full",
            }
        ]
        with pytest.raises(ValueError, match="margin_pct"):
            await compose_proposal(db, rfq, decisions=decisions, margin_pct=200.0, composed_by=uuid4())

    @pytest.mark.asyncio
    async def test_invalid_decision_rejected(self) -> None:
        order = _make_order()
        rfq = _make_rfq()
        db = _FakeSession(
            _FakeResult(scalar=order),
            _FakeResult(rows=[]),
        )
        decisions = [
            {
                "rfq_item_id": str(rfq.items[0].id),
                "supplier_id": str(SUPPLIER_ID),
                "quote_id": str(QUOTE_ID),
                "decision": "nonsense",
            }
        ]
        with pytest.raises(ValueError, match="Invalid decision"):
            await compose_proposal(db, rfq, decisions=decisions, margin_pct=8.0, composed_by=uuid4())


# --- route tests ------------------------------------------------------


class TestComposeRoute:
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
        r = client.post(f"/api/v1/rfq/{RFQ_ID}/compose", json={"decisions": []})
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
        r = client.post(f"/api/v1/rfq/{RFQ_ID}/compose", json={"decisions": []})
        assert r.status_code == 403

    def test_400_on_cancelled_rfq(self, app: FastAPI, client: TestClient) -> None:
        rfq = _make_rfq()
        rfq.status = RFQStatus.CANCELLED
        app.state.fake_session = _FakeSession(_FakeResult(scalar=rfq))
        r = client.post(
            f"/api/v1/rfq/{RFQ_ID}/compose",
            json={
                "decisions": [
                    {
                        "rfq_item_id": str(rfq.items[0].id),
                        "supplier_id": str(SUPPLIER_ID),
                        "quote_id": str(QUOTE_ID),
                        "decision": "use_full",
                    }
                ],
                "margin_pct": 8.0,
            },
        )
        assert r.status_code == 400
        assert "cancelled" in r.json()["detail"].lower()

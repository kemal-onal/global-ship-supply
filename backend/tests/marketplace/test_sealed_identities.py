"""Sealed-bid identity tests for the marketplace flow.

The marketplace redesign keeps the 3-tier redaction:
  * purchasers don't see supplier names or unit_price
  * suppliers don't see the vessel's real name
  * admins see everything

The new endpoints (``/orders/{id}/proposal`` for purchasers,
``/supplier-portal/rfqs`` for suppliers) must continue to
respect these rules. A single leak in any direction would
break the demo's value prop.

These tests focus on the wire shape: the field is *absent* (not
just null) when sealed, so the UI knows to hide the column.
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
from app.models.supplier import AssignmentStatus, RFQStatus, Supplier
from app.models.user import User
from app.services.redaction import (
    hides_prices,
    is_supplier,
    seal_order_for_purchaser,
    seal_order_for_supplier,
)


# --- helpers ----------------------------------------------------------


SUPPLIER_EMAIL = "supplier@apcmarine.sg"
SUPPLIER_ID = uuid4()
USER_ID = uuid4()
VESSEL_ID = uuid4()
ORDER_ID = uuid4()
RFQ_ID = uuid4()
PRODUCT_ID = uuid4()


def _purchaser_token() -> TokenData:
    return TokenData(
        sub="test-purchaser",
        roles=["purchasing_officer"],
        permissions=["marketplace:approve:own", "orders:read"],
        vessel_id=VESSEL_ID,
    )


def _admin_token() -> TokenData:
    return TokenData(
        sub="test-admin",
        roles=["super_admin"],
        permissions=["marketplace:compose:global", "orders:read"],
        vessel_id=VESSEL_ID,
    )


def _supplier_token() -> TokenData:
    return TokenData(
        sub=str(USER_ID),
        roles=["supplier"],
        permissions=["supplier_portal:view:global"],
        vessel_id=None,
    )


# --- direct redaction helper tests ------------------------------------


class TestRedactionHelpers:
    """Sanity checks on the redaction primitives. The route tests
    below assume these work as documented here."""

    def test_hides_prices_for_purchaser(self) -> None:
        assert hides_prices(["purchasing_officer"]) is True

    def test_does_not_hide_prices_for_admin(self) -> None:
        assert hides_prices(["super_admin"]) is False

    def test_is_supplier(self) -> None:
        assert is_supplier(["supplier"]) is True
        assert is_supplier(["purchasing_officer"]) is False

    def test_seal_order_for_purchaser_strips_unit_price(self) -> None:
        # The seal function takes a dict payload and returns the
        # same shape minus price-bearing fields. The marketplace
        # proposal route applies this filter (in addition to
        # removing supplier identity at the route level).
        payload = {
            "id": "x",
            "supplier_id": "abc",
            "supplier_name": "APC",
            "subtotal": 100.0,
            "tax_total": 10.0,
            "shipping_total": 5.0,
            "grand_total": 115.0,
            "currency": "USD",
            "items": [
                {"id": "i1", "unit_price": 10.0, "line_total": 100.0, "quantity": 10}
            ],
        }
        out = seal_order_for_purchaser(payload)
        # Top-level monetary fields are zeroed
        assert out.get("subtotal") is None
        assert out.get("tax_total") is None
        assert out.get("shipping_total") is None
        assert out.get("grand_total") is None
        assert out.get("currency") is None
        # Per-item monetary fields are zeroed
        assert out["items"][0]["unit_price"] is None
        assert out["items"][0]["line_total"] is None
        # Non-monetary fields preserved
        assert out["items"][0]["quantity"] == 10
        # The seal function doesn't touch supplier identity at
        # the order level; the marketplace route does that
        # explicitly. We don't test that here.

    def test_seal_order_for_supplier_renames_vessel(self) -> None:
        # supplier view of an order shouldn't expose the vessel's
        # real name. The seal function should either drop the
        # field or replace it with an anonymized label.
        payload = {
            "id": "x",
            "vessel_id": str(VESSEL_ID),
            "vessel_name": "MV Sealand",
        }
        out = seal_order_for_supplier(payload)
        # The vessel_name field is either absent or not the real
        # name. Either is acceptable as long as the real name
        # doesn't leak.
        vname = out.get("vessel_name")
        if vname is not None:
            assert vname != "MV Sealand"


# --- supplier view: vessel anonymization ------------------------------


class TestSupplierViewSealsVessel:
    @pytest.fixture
    def app(self) -> FastAPI:
        a = FastAPI()
        a.include_router(api_router, prefix="/api/v1")

        from tests.marketplace.test_supplier_portal import _FakeResult, _FakeSession
        a.state.fake_session = _FakeSession()
        a.state.fake_user = SimpleNamespace(
            id=USER_ID, email=SUPPLIER_EMAIL, roles=["supplier"]
        )
        a.state.fake_supplier = SimpleNamespace(
            id=SUPPLIER_ID, company_name="APC Marine", contact_email=SUPPLIER_EMAIL
        )

        def _sess():
            return a.state.fake_session

        def _token():
            return _supplier_token()

        a.dependency_overrides[db_session] = _sess
        a.dependency_overrides[read_db_session] = _sess
        a.dependency_overrides[get_current_token] = _token
        return a

    @pytest.fixture
    def client(self, app: FastAPI) -> TestClient:
        return TestClient(app)

    def test_list_rfqs_never_returns_real_vessel_name(self, app: FastAPI, client: TestClient) -> None:
        from tests.marketplace.test_supplier_portal import _FakeResult, _FakeSession
        rfq = SimpleNamespace(
            id=RFQ_ID,
            reference="RFQ-TEST-0001",
            order_id=ORDER_ID,
            port_id=uuid4(),
            status=RFQStatus.SENT,
            sent_at=datetime.now(timezone.utc),
            response_deadline=datetime.now(timezone.utc),
            responded_count=0,
            invited_count=1,
            extra={"invited_supplier_ids": [str(SUPPLIER_ID)]},
            items=[],
            order=SimpleNamespace(
                id=ORDER_ID,
                reference="AVS-TEST-0001",
                vessel_id=VESSEL_ID,
                vessel=SimpleNamespace(id=VESSEL_ID, name="MV Sealand"),
                # IMPA-first ETA/ETD (migration 0007). The
                # supplier portal route surfaces these so the
                # supplier can decide on the gate. None in this
                # test — no AIS snapshot in the test data.
                eta_at_port=None,
                etd_at_port=None,
            ),
            quotes=[],
        )
        app.state.fake_session = _FakeSession(
            _FakeResult(scalar=app.state.fake_user),
            _FakeResult(scalar=app.state.fake_supplier),
            _FakeResult(rows=[rfq]),
        )
        r = client.get("/api/v1/supplier-portal/rfqs")
        assert r.status_code == 200
        body = r.json()
        for row in body:
            # The real vessel name MUST NOT appear anywhere
            assert "Sealand" not in str(row)
            # And a stable anonymized label IS present
            assert row["vessel_label"].startswith("Vessel #")

    def test_get_rfq_never_returns_real_vessel_name(self, app: FastAPI, client: TestClient) -> None:
        from tests.marketplace.test_supplier_portal import _FakeResult, _FakeSession
        rfq = SimpleNamespace(
            id=RFQ_ID,
            reference="RFQ-TEST-0001",
            order_id=ORDER_ID,
            port_id=uuid4(),
            status=RFQStatus.SENT,
            sent_at=datetime.now(timezone.utc),
            response_deadline=datetime.now(timezone.utc),
            extra={"invited_supplier_ids": [str(SUPPLIER_ID)]},
            items=[SimpleNamespace(
                id=uuid4(), product_id=PRODUCT_ID, quantity=1, unit="pcs",
                description="Boot", impa_code="632121",
            )],
            order=SimpleNamespace(
                id=ORDER_ID, vessel_id=VESSEL_ID,
                vessel=SimpleNamespace(id=VESSEL_ID, name="MV Sealand"),
                eta_at_port=None,
                etd_at_port=None,
            ),
            quotes=[],
        )
        app.state.fake_session = _FakeSession(
            _FakeResult(scalar=app.state.fake_user),
            _FakeResult(scalar=app.state.fake_supplier),
            _FakeResult(scalar=rfq),
        )
        r = client.get(f"/api/v1/supplier-portal/rfqs/{RFQ_ID}")
        assert r.status_code == 200
        body = r.json()
        # The vessel_label is anonymized
        assert "Sealand" not in body["vessel_label"]
        assert body["vessel_label"].startswith("Vessel #")


# --- purchaser view: supplier anonymization --------------------------


class TestPurchaserViewSealsSupplier:
    @pytest.fixture
    def app(self) -> FastAPI:
        a = FastAPI()
        a.include_router(api_router, prefix="/api/v1")
        a.state.fake_session = _FakeSession_default()
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

    def test_proposal_response_never_returns_supplier_name(self, app: FastAPI, client: TestClient) -> None:
        # Set up an order + decision with a real supplier name.
        order = SimpleNamespace(
            id=ORDER_ID,
            reference="AVS-TEST-0001",
            vessel_id=VESSEL_ID,
            port_id=uuid4(),
            status=OrderStatus.AWAITING_PURCHASER_APPROVAL,
            company_margin_pct=8.0,
            eta_at_port=None,
        )
        decision = SimpleNamespace(
            id=uuid4(),
            order_id=ORDER_ID,
            rfq_item_id=uuid4(),
            supplier_id=SUPPLIER_ID,
            quote_id=uuid4(),
            decision="use_full",
            unit_price=10.0,
            used_quantity=10,
            line_total=100.0,
            margin_pct=8.0,
            customer_facing_total=108.0,
            rfq_item=SimpleNamespace(product_id=PRODUCT_ID),
            supplier=SimpleNamespace(company_name="APC Marine"),  # the leak
            quote=SimpleNamespace(lead_time_days=7),
        )
        from tests.marketplace.test_supplier_portal import _FakeResult
        app.state.fake_session = _FakeSession_default(
            _FakeResult(scalar=order),
            _FakeResult(rows=[decision]),
        )
        r = client.get(f"/api/v1/orders/{ORDER_ID}/proposal")
        assert r.status_code == 200
        body = r.json()
        # Walk the response, the supplier name MUST NOT appear
        # anywhere — including nested under any other key.
        raw = r.text
        assert "APC Marine" not in raw
        assert str(SUPPLIER_ID) not in raw
        # And the per-line dict has no supplier identity fields
        line = body["lines"][0]
        assert "supplier_id" not in line
        assert "supplier_name" not in line
        # line_total is null (purchaser doesn't see it)
        assert line["line_total"] is None
        # customer_facing_total is visible
        assert line["customer_facing_total"] is not None


# --- shared helpers --------------------------------------------------


class _FakeResult_default:
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


class _FakeSession_default:
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
            return _FakeResult_default(scalar=None)
        return self._queue.pop(0)

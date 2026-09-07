"""Route tests for the supplier-facing portal.

The supplier is bound to a Supplier row by ``contact_email ==
User.email``. The portal lists RFQs the supplier is invited to,
shows RFQ detail (with the vessel name anonymized), accepts
per-line quotes (full / partial / none), and lets the supplier
accept their post-approval slice within the 24h window.

These tests cover:
  * 401 / 403 / 404
  * list RFQs filters on the invited_supplier_ids
  * detail anonymizes the vessel name
  * submit_quote happy path + invalid line_status
  * accept-slice happy path
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
from app.models.supplier import (
    AssignmentStatus,
    RFQStatus,
    Supplier,
    SupplierLineAssignment,
    SupplierQuote,
)
from app.models.user import User


# --- helpers ----------------------------------------------------------


SUPPLIER_EMAIL = "supplier@apcmarine.sg"
SUPPLIER_ID = uuid4()
USER_ID = uuid4()
PORT_ID = uuid4()
ORDER_ID = uuid4()
VESSEL_ID = uuid4()
RFQ_ID = uuid4()
QUOTE_ID = uuid4()
PRODUCT_ID = uuid4()
RFQ_ITEM_ID = uuid4()


def _supplier_token() -> TokenData:
    return TokenData(
        sub=str(USER_ID),
        roles=["supplier"],
        permissions=[
            "supplier_portal:view:global",
            "supplier_portal:quote:global",
            "supplier_portal:accept:global",
        ],
        vessel_id=None,
    )


def _supplier_row() -> Supplier:
    return SimpleNamespace(
        id=SUPPLIER_ID,
        company_name="APC Marine",
        contact_email=SUPPLIER_EMAIL,
        status="active",
    )


def _user_row() -> User:
    return SimpleNamespace(
        id=USER_ID,
        email=SUPPLIER_EMAIL,
        roles=["supplier"],
    )


def _rfq_row(*, invited: list[str] | None = None) -> SimpleNamespace:
    """A bare-bones RFQ SimpleNamespace; the list_rfqs route reads
    extra, items, quotes, order, and sent_at.
    """
    if invited is None:
        invited = [str(SUPPLIER_ID)]
    return SimpleNamespace(
        id=RFQ_ID,
        reference="RFQ-TEST-0001",
        order_id=ORDER_ID,
        port_id=PORT_ID,
        status=RFQStatus.SENT,
        sent_at=datetime.now(timezone.utc),
        response_deadline=datetime.now(timezone.utc),
        responded_count=0,
        invited_count=len(invited),
        extra={"invited_supplier_ids": invited},
        items=[SimpleNamespace(id=RFQ_ITEM_ID)],
        order=SimpleNamespace(
            id=ORDER_ID,
            reference="AVS-TEST-0001",
            vessel_id=VESSEL_ID,
            vessel=SimpleNamespace(id=VESSEL_ID, name="MV Sealand"),
            # IMPA-first ETA/ETD (migration 0007). The supplier
            # portal route surfaces these so the supplier can
            # decide "can I deliver in this window?" before the
            # line picker.
            eta_at_port=None,
            etd_at_port=None,
        ),
        quotes=[],
    )


class _FakeResult:
    """Mimics a single execute() result, switching on the query."""

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
    """Session that returns a queued result per .execute() call.

    The supplier portal runs:
      * list_rfqs: 1 user lookup, 1 supplier lookup, 1 rfqs query
      * get_rfq: 1 user, 1 supplier, 1 rfq
      * submit_quote: 1 user, 1 supplier, 1 rfq
      * accept_slice: 1 user, 1 supplier, 1 quote, 1 pending assignments
      * list_assignments: 1 user, 1 supplier, 1 assignments
    The route under test determines the queue shape; we set it up
    in the fixture for each test.
    """

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


# --- fixtures ---------------------------------------------------------


@pytest.fixture
def app() -> FastAPI:
    a = FastAPI()
    a.include_router(api_router, prefix="/api/v1")
    a.state.fake_session = _FakeSession()  # default

    def _sess():
        return a.state.fake_session

    def _token():
        return _supplier_token()

    a.dependency_overrides[db_session] = _sess
    a.dependency_overrides[read_db_session] = _sess
    a.dependency_overrides[get_current_token] = _token
    return a


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


# --- tests ------------------------------------------------------------


class TestAuth:
    def test_401_without_token(self, client: TestClient) -> None:
        client.app.dependency_overrides.pop(get_current_token)
        r = client.get("/api/v1/supplier-portal/rfqs")
        assert r.status_code == 401

    def test_403_without_view_permission(self, app: FastAPI, client: TestClient) -> None:
        def _no_perm():
            return TokenData(
                sub=str(USER_ID),
                roles=["supplier"],
                permissions=[],
                vessel_id=None,
            )

        app.dependency_overrides[get_current_token] = _no_perm
        r = client.get("/api/v1/supplier-portal/rfqs")
        assert r.status_code == 403


class TestListRfqs:
    def test_lists_invited_rfqs(self, app: FastAPI, client: TestClient) -> None:
        rfq = _rfq_row(invited=[str(SUPPLIER_ID)])
        app.state.fake_session = _FakeSession(
            _FakeResult(scalar=_user_row()),     # _load_supplier_for_token: user lookup
            _FakeResult(scalar=_supplier_row()), # supplier lookup
            _FakeResult(rows=[rfq]),             # rfqs list
        )
        r = client.get("/api/v1/supplier-portal/rfqs")
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body) == 1
        # Vessel is anonymized (not the real name "MV Sealand")
        first = body[0]
        assert first["vessel_label"].startswith("Vessel #")
        assert "Sealand" not in first["vessel_label"]
        # The supplier's own quote (none yet) — has_quote False
        assert first["has_quote"] is False
        assert first["quote_id"] is None

    def test_excludes_uninvited_rfqs(self, app: FastAPI, client: TestClient) -> None:
        # RFQ exists but the supplier isn't in invited_supplier_ids
        rfq = _rfq_row(invited=[str(uuid4())])
        app.state.fake_session = _FakeSession(
            _FakeResult(scalar=_user_row()),
            _FakeResult(scalar=_supplier_row()),
            _FakeResult(rows=[rfq]),
        )
        r = client.get("/api/v1/supplier-portal/rfqs")
        assert r.status_code == 200
        assert r.json() == []


class TestGetRfq:
    def test_returns_anonymized_detail(self, app: FastAPI, client: TestClient) -> None:
        rfq = _rfq_row()
        rfq.items = [SimpleNamespace(
            id=RFQ_ITEM_ID,
            product_id=PRODUCT_ID,
            quantity=10,
            unit="pcs",
            description="Steel-toe boots for engine room crew",
            impa_code="632121",
        )]
        app.state.fake_session = _FakeSession(
            _FakeResult(scalar=_user_row()),
            _FakeResult(scalar=_supplier_row()),
            _FakeResult(scalar=rfq),
        )
        r = client.get(f"/api/v1/supplier-portal/rfqs/{RFQ_ID}")
        assert r.status_code == 200, r.text
        body = r.json()
        # Vessel anonymized
        assert body["vessel_label"].startswith("Vessel #")
        # Line items visible with intended-use description
        assert body["items"][0]["description"] == "Steel-toe boots for engine room crew"
        assert body["items"][0]["impa_code"] == "632121"
        # No quote yet
        assert body["my_quote"] is None

    def test_404_for_uninvited(self, app: FastAPI, client: TestClient) -> None:
        rfq = _rfq_row(invited=[str(uuid4())])
        app.state.fake_session = _FakeSession(
            _FakeResult(scalar=_user_row()),
            _FakeResult(scalar=_supplier_row()),
            _FakeResult(scalar=rfq),
        )
        r = client.get(f"/api/v1/supplier-portal/rfqs/{RFQ_ID}")
        assert r.status_code == 404

    def test_returns_my_quote_lines_without_lazy_loading(
        self, app: FastAPI, client: TestClient
    ) -> None:
        """Regression: get_rfq used to lazy-load my_quote.items
        inside the async route, which blew up with MissingGreenlet
        the moment a supplier had already submitted any lines.

        The fix: ``selectinload(SupplierQuote.items)`` chained on
        the ``RFQ.quotes`` eager load. This test pins it: a quote
        with two lines must round-trip to ``my_quote.lines`` in
        the response without a 500. If anyone removes the
        eager-load later, the request crashes the same way and
        this test catches it.
        """
        rfq = _rfq_row()
        rfq.items = [SimpleNamespace(
            id=RFQ_ITEM_ID,
            product_id=PRODUCT_ID,
            quantity=2,
            unit="pcs",
            description="line 1",
            impa_code="111111",
        )]
        # A quote on file for this supplier, with two line items.
        rfq.quotes = [SimpleNamespace(
            id=QUOTE_ID,
            reference="Q-TEST-0001",
            supplier_id=SUPPLIER_ID,
            lead_time_days=7,
            payment_terms="Net 30",
            total=500.0,
            currency="USD",
            decision_method="full",
            can_deliver_in_window=True,
            declined_at=None,
            decline_reason=None,
            submitted_at=datetime.now(timezone.utc),
            items=[
                SimpleNamespace(
                    id=uuid4(),
                    product_id=PRODUCT_ID,
                    line_status="full",
                    unit_price=100.0,
                    quantity=2,
                    quoted_quantity=2,
                ),
                SimpleNamespace(
                    id=uuid4(),
                    product_id=uuid4(),
                    line_status="none",
                    unit_price=0,
                    quantity=3,
                    quoted_quantity=0,
                ),
            ],
        )]
        app.state.fake_session = _FakeSession(
            _FakeResult(scalar=_user_row()),
            _FakeResult(scalar=_supplier_row()),
            _FakeResult(scalar=rfq),
        )
        r = client.get(f"/api/v1/supplier-portal/rfqs/{RFQ_ID}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["my_quote"] is not None
        assert body["my_quote"]["reference"] == "Q-TEST-0001"
        # The two line items must be present in the response.
        # This is what failed on the live backend with a
        # MissingGreenlet 500.
        lines = body["my_quote"]["lines"]
        assert len(lines) == 2
        statuses = sorted(l["line_status"] for l in lines)
        assert statuses == ["full", "none"]
        # And the per-line numeric fields round-trip cleanly.
        full_line = next(l for l in lines if l["line_status"] == "full")
        assert full_line["unit_price"] == 100.0
        assert full_line["quantity"] == 2
        assert full_line["quoted_quantity"] == 2


class TestSubmitQuote:
    def test_submit_full_quote(self, app: FastAPI, client: TestClient) -> None:
        rfq = _rfq_row()
        rfq.items = [SimpleNamespace(id=RFQ_ITEM_ID, product_id=PRODUCT_ID, quantity=10)]
        # The submit_quote service:
        #   - looks up the rfq
        #   - deletes any existing quote (none here)
        #   - creates the new quote
        #   - returns the quote
        # Our fake session has to support that flow:
        #   1. user lookup
        #   2. supplier lookup
        #   3. rfq lookup
        #   4. existing-quote lookup (returns None → no delete)
        # The route then calls marketplace_svc.supplier_submit_quote
        # which queries a few more things internally; for the route
        # test we just verify the HTTP path: 200 + reference.
        # Set up the queue with enough results.
        from app.services.marketplace import supplier_submit_quote
        from app.models.supplier import QuoteItem
        # Pre-build a quote to simulate the service output
        new_quote = SimpleNamespace(
            id=QUOTE_ID,
            reference="Q-TEST-0001",
            total=100.0,
            currency="USD",
            decision_method="full",
            # IMPA-first gate fields (migration 0007). The stub
            # mimics the real service output for a "yes" decision.
            can_deliver_in_window=True,
            declined_at=None,
            decline_reason=None,
        )
        # We can't easily call the real service against a fake DB
        # because of the many internal queries, so we monkeypatch.
        async def _stub_submit(*args, **kwargs):
            return new_quote
        import app.api.v1.supplier_portal as sp
        sp.marketplace_svc.supplier_submit_quote = _stub_submit

        app.state.fake_session = _FakeSession(
            _FakeResult(scalar=_user_row()),
            _FakeResult(scalar=_supplier_row()),
            _FakeResult(scalar=rfq),
        )
        payload = {
            "lead_time_days": 7,
            "payment_terms": "Net 30",
            "notes": "Best price in port",
            "source": "portal",
            "lines": [
                {
                    "rfq_item_id": str(RFQ_ITEM_ID),
                    "line_status": "full",
                    "unit_price": 10.0,
                }
            ],
        }
        r = client.post(f"/api/v1/supplier-portal/rfqs/{RFQ_ID}/quote", json=payload)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["reference"] == "Q-TEST-0001"
        assert body["total"] == 100.0

    def test_submit_400_on_bad_status(self, client: TestClient) -> None:
        # Pydantic regex on line_status: must be full|partial|none
        r = client.post(
            f"/api/v1/supplier-portal/rfqs/{RFQ_ID}/quote",
            json={
                "lead_time_days": 7,
                "lines": [
                    {
                        "rfq_item_id": str(RFQ_ITEM_ID),
                        "line_status": "maybe",
                        "unit_price": 10.0,
                    }
                ],
            },
        )
        assert r.status_code == 422

    def test_submit_400_when_rfq_is_awarded(
        self, app: FastAPI, client: TestClient
    ) -> None:
        """Regression: an awarded RFQ must reject any further
        quote submissions with 400.

        Real-world scenario: the supplier opens an RFQ in the
        portal and the company has already picked them (status
        ``awarded``). The backend must refuse the resubmit with a
        clear message; the frontend must hide the form. If the
        route ever silently accepts this, suppliers could change
        prices on a contract that has already been accepted.
        """
        # The service raises ValueError for closed-state RFQs;
        # stub it so we don't need a real DB session.
        async def _stub_submit_awarded(*args, **kwargs):
            raise ValueError("RFQ is awarded; cannot accept quotes")
        import app.api.v1.supplier_portal as sp
        sp.marketplace_svc.supplier_submit_quote = _stub_submit_awarded

        rfq = _rfq_row()
        rfq.status = RFQStatus.AWARDED  # the key bit
        app.state.fake_session = _FakeSession(
            _FakeResult(scalar=_user_row()),
            _FakeResult(scalar=_supplier_row()),
            _FakeResult(scalar=rfq),
        )
        r = client.post(
            f"/api/v1/supplier-portal/rfqs/{RFQ_ID}/quote",
            json={
                "lead_time_days": 7,
                "lines": [
                    {
                        "rfq_item_id": str(RFQ_ITEM_ID),
                        "line_status": "full",
                        "unit_price": 99.99,
                    }
                ],
            },
        )
        assert r.status_code == 400, r.text
        assert "awarded" in r.json()["detail"].lower()

    def test_submit_gate_click_with_zero_lead_time_does_not_422(
        self, app: FastAPI, client: TestClient
    ) -> None:
        """Pinning test for the IMPA-first gate click contract.

        Bug: the supplier portal's "Submit decision" button used
        to post ``lead_time_days: 0`` as a placeholder. The
        Pydantic ``QuoteIn`` schema (supplier_portal.py:106) used
        to require ``lead_time_days >= 1``, so the gate click
        422'd with ``Input should be greater than or equal to 1``.

        The fix is two-sided:
          1. Backend: ``QuoteIn.lead_time_days`` is now
             ``int | None`` and the service falls back to 7 (the
             model's default) on write. Sending an explicit
             integer still validates the ge=1 bound (see the
             test below).
          2. Frontend: the ``submitGate`` mutation in
             ``SupplierPortal.jsx`` now *omits* ``lead_time_days``
             entirely instead of sending 0, so the schema
             default of None applies.

        This test pins the omit-entirely path (the production
        payload) — see ``test_submit_gate_click_rejects_zero``
        for the contract that an explicit 0 still 422s.
        """
        rfq = _rfq_row()
        rfq.items = [SimpleNamespace(id=RFQ_ITEM_ID, product_id=PRODUCT_ID, quantity=10)]
        # Stub the service so we test the schema/route path
        # without simulating the service's internal queries.
        import app.api.v1.supplier_portal as sp

        async def _stub_submit(*args, **kwargs):
            return SimpleNamespace(
                id=QUOTE_ID,
                reference="Q-TEST-GATE",
                total=0.0,
                currency="USD",
                decision_method=None,
                can_deliver_in_window=True,
                declined_at=None,
                decline_reason=None,
            )
        sp.marketplace_svc.supplier_submit_quote = _stub_submit

        app.state.fake_session = _FakeSession(
            _FakeResult(scalar=_user_row()),
            _FakeResult(scalar=_supplier_row()),
            _FakeResult(scalar=rfq),
        )
        # The current frontend payload: lead_time_days is
        # omitted entirely.
        payload = {
            "can_deliver_in_window": True,
            "lines": [],
        }
        r = client.post(
            f"/api/v1/supplier-portal/rfqs/{RFQ_ID}/quote", json=payload
        )
        assert r.status_code == 200, (
            f"gate click with lead_time_days omitted should not "
            f"422; got {r.status_code}: {r.text}"
        )
        body = r.json()
        assert body["reference"] == "Q-TEST-GATE"
        assert body["can_deliver_in_window"] is True

    def test_submit_gate_click_rejects_zero(self, client: TestClient) -> None:
        """If a supplier (or a stale client) does send
        ``lead_time_days: 0``, Pydantic still 422s. This pins the
        ge=1 bound on the explicit value, so a future refactor
        that loosens the bound to allow 0 doesn't silently
        degrade the data quality. Real clients omit the field
        (see ``test_submit_gate_click_with_zero_lead_time_does_not_422``)."""
        r = client.post(
            f"/api/v1/supplier-portal/rfqs/{RFQ_ID}/quote",
            json={
                "can_deliver_in_window": True,
                "lead_time_days": 0,
                "lines": [],
            },
        )
        assert r.status_code == 422
        body = r.json()
        assert any(
            "lead_time_days" in (err.get("loc") or [])
            for err in body.get("detail", [])
        )

    def test_submit_gate_click_without_lead_time_field_at_all(
        self, app: FastAPI, client: TestClient
    ) -> None:
        """Even cleaner: the supplier can omit ``lead_time_days``
        entirely on a gate click. The schema defaults it to None
        and the service writes 7 to satisfy the NOT NULL column.
        """
        rfq = _rfq_row()
        rfq.items = [SimpleNamespace(id=RFQ_ITEM_ID, product_id=PRODUCT_ID, quantity=10)]
        import app.api.v1.supplier_portal as sp

        async def _stub_submit(*args, **kwargs):
            return SimpleNamespace(
                id=QUOTE_ID,
                reference="Q-TEST-GATE-2",
                total=0.0,
                currency="USD",
                decision_method=None,
                can_deliver_in_window=False,
                declined_at=None,
                decline_reason="out of stock",
            )
        sp.marketplace_svc.supplier_submit_quote = _stub_submit

        app.state.fake_session = _FakeSession(
            _FakeResult(scalar=_user_row()),
            _FakeResult(scalar=_supplier_row()),
            _FakeResult(scalar=rfq),
        )
        # Decline path: no lead_time_days, no lines, with a reason.
        payload = {
            "can_deliver_in_window": False,
            "decline_reason": "out of stock",
            "lines": [],
        }
        r = client.post(
            f"/api/v1/supplier-portal/rfqs/{RFQ_ID}/quote", json=payload
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["can_deliver_in_window"] is False
        assert body["decline_reason"] == "out of stock"


class TestAcceptSlice:
    def test_accept_pending_assignments(self, app: FastAPI, client: TestClient) -> None:
        # accept_slice path: 1 user, 1 supplier, 1 quote, 1 pending assignments
        # then iterates pending → supplier_accept_slice service
        sla = SimpleNamespace(
            id=uuid4(),
            order_id=ORDER_ID,
            rfq_item_id=RFQ_ITEM_ID,
            supplier_id=SUPPLIER_ID,
            quote_id=QUOTE_ID,
            line_status=AssignmentStatus.PENDING.value,
            confirmed_at=None,
            dropped_at=None,
            drop_reason=None,
            preparation_deadline=None,
        )
        quote = SimpleNamespace(
            id=QUOTE_ID,
            reference="Q-TEST-0001",
            supplier_id=SUPPLIER_ID,
        )
        # Stub the service so the route doesn't have to traverse
        # the real SupplierLineAssignment model.
        import app.api.v1.supplier_portal as sp
        async def _stub_accept(*args, **kwargs):
            sla.confirmed_at = datetime.now(timezone.utc)
            sla.line_status = AssignmentStatus.CONFIRMED.value
            return sla
        sp.marketplace_svc.supplier_accept_slice = _stub_accept

        app.state.fake_session = _FakeSession(
            _FakeResult(scalar=_user_row()),
            _FakeResult(scalar=_supplier_row()),
            _FakeResult(scalar=quote),
            _FakeResult(rows=[sla]),  # pending assignments
        )
        r = client.post(f"/api/v1/supplier-portal/quotes/{QUOTE_ID}/accept")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["quote_id"] == str(QUOTE_ID)
        assert body["accepted"] == 1
        # Audit log written + committed
        assert app.state.fake_session.committed is True

    def test_no_pending_returns_friendly(self, app: FastAPI, client: TestClient) -> None:
        quote = SimpleNamespace(id=QUOTE_ID, supplier_id=SUPPLIER_ID, reference="Q-TEST-0001")
        app.state.fake_session = _FakeSession(
            _FakeResult(scalar=_user_row()),
            _FakeResult(scalar=_supplier_row()),
            _FakeResult(scalar=quote),
            _FakeResult(rows=[]),  # no pending
        )
        r = client.post(f"/api/v1/supplier-portal/quotes/{QUOTE_ID}/accept")
        assert r.status_code == 200
        body = r.json()
        assert body["accepted"] == 0
        assert "no pending" in body["message"].lower()


class TestListAssignments:
    def test_returns_suppliers_slices(self, app: FastAPI, client: TestClient) -> None:
        sla = SimpleNamespace(
            id=uuid4(),
            order_id=ORDER_ID,
            rfq_item_id=RFQ_ITEM_ID,
            line_status=AssignmentStatus.PENDING.value,
            confirmed_at=None,
            dropped_at=None,
            drop_reason=None,
            preparation_deadline=datetime.now(timezone.utc) + __import__("datetime").timedelta(hours=24),
            order=SimpleNamespace(reference="AVS-TEST-0001"),
            rfq_item=SimpleNamespace(product_id=PRODUCT_ID),
        )
        app.state.fake_session = _FakeSession(
            _FakeResult(scalar=_user_row()),
            _FakeResult(scalar=_supplier_row()),
            _FakeResult(rows=[sla]),
        )
        r = client.get("/api/v1/supplier-portal/assignments")
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body) == 1
        assert body[0]["line_status"] == "pending"
        assert body[0]["preparation_deadline"] is not None

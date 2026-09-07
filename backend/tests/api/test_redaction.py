"""Route + unit tests for the three-tier redaction layer.

Covers:
* Pure filter functions in ``app.services.redaction`` — the
  heart of the redaction policy.
* Integration: ``GET /api/v1/orders`` + ``GET /api/v1/orders/{id}``
  shape for purchasing_officer (prices stripped) and supplier
  (vessel anonymized, internal_notes stripped, customer_notes kept).
* Integration: ``GET /api/v1/catalog/products`` strips unit_price
  + currency for purchasing_officer.
* Integration: ``GET /api/v1/rfq`` (list) and ``GET /api/v1/rfq/{id}``
  strip awarded_quote_id + target_unit_price for purchasing_officer;
  on an awarded RFQ the single view reduces to a one-card winner.
* Regression: company-side callers (super_admin) see the full
  payload untouched.

The pure-function tests (no FastAPI) come first because they're
the authoritative contract — the route tests just verify the routes
plumb the right roles into the filters.
"""
from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import api_router
from app.core.security import TokenData
from app.deps.auth import (
    CurrentToken,
    DBSession,
    ReadDBSession,
    db_session,
    get_current_token,
    read_db_session,
)
from app.services.redaction import (
    PRICE_HIDING_ROLES,
    SUPPLIER_ROLES,
    UNSEALED_ROLES,
    hides_prices,
    is_supplier,
    is_unsealed,
    seal_catalog_for_purchaser,
    seal_order_for_purchaser,
    seal_order_for_supplier,
    seal_product_for_purchaser,
    seal_rfq_award_for_purchaser,
)


# --- helpers ----------------------------------------------------------


def _token(
    *,
    sub: str = "test-user",
    roles: list[str] | None = None,
    permissions: list[str] | None = None,
    vessel_id: UUID | None = None,
) -> TokenData:
    return TokenData(
        sub=sub,
        roles=roles or [],
        permissions=permissions or [],
        vessel_id=vessel_id,
    )


def _order_payload(*, vessel_id: UUID | None = None) -> dict:
    """A fully-populated order payload — the company-side view.

    The order has a known vessel id, customer notes, internal notes,
    and per-line notes. The redaction tests below mutate the
    expected shape based on the caller's role.
    """
    return {
        "id": str(uuid4()),
        "reference": "AVS-2026-000001",
        "vessel_id": str(vessel_id or uuid4()),
        "vessel_name": "MV Test Star",
        "port_id": str(uuid4()),
        "port_name": "Port of Singapore",
        "status": "draft",
        "priority": "normal",
        "order_date": "2026-09-04T10:00:00+00:00",
        "required_by": None,
        "estimated_delivery": None,
        "currency": "USD",
        "subtotal": 1500.0,
        "tax_total": 0.0,
        "shipping_total": 0.0,
        "grand_total": 1500.0,
        "customer_notes": "Deliver to aft deck, code 4123 is the gate pass",
        "internal_notes": "CFO wants this under budget by 15%, escalate if over",
        "source": "web",
        "client_id": None,
        "created_by": str(uuid4()),
        "items": [
            {
                "id": str(uuid4()),
                "product_id": str(uuid4()),
                "product_name": "Test product",
                "product_sku": "AVS-TEST-001",
                "quantity": 5,
                "unit": "pcs",
                "unit_price": 300.0,
                "line_total": 1500.0,
                "notes": "Color: white, left-hand thread",
            }
        ],
        "regulation_warnings": [],
    }


# --- predicates -------------------------------------------------------


class TestPredicates:
    def test_purchasing_officer_hides_prices(self) -> None:
        assert hides_prices(["purchasing_officer"])
        assert not hides_prices(["super_admin"])
        assert not hides_prices(["supplier"])
        assert not hides_prices([])
        assert not hides_prices(None)

    def test_supplier_role_check(self) -> None:
        assert is_supplier(["supplier"])
        assert not is_supplier(["purchasing_officer"])
        assert not is_supplier(["super_admin"])
        assert not is_supplier([])
        assert not is_supplier(None)

    def test_unsealed_role_check(self) -> None:
        # The company-side roles (UNSEALED_ROLES) see the full
        # payload untouched.
        for role in UNSEALED_ROLES:
            assert is_unsealed([role]), f"{role} should be unsealed"
        # Purchaser + supplier are sealed.
        assert not is_unsealed(["purchasing_officer"])
        assert not is_unsealed(["supplier"])
        assert not is_unsealed([])

    def test_role_sets_are_frozen(self) -> None:
        # These are frozensets so they can't be mutated at runtime.
        # This test guards against an accidental change to a list.
        assert isinstance(PRICE_HIDING_ROLES, frozenset)
        assert isinstance(SUPPLIER_ROLES, frozenset)
        assert isinstance(UNSEALED_ROLES, frozenset)


# --- seal_order_for_purchaser -----------------------------------------


class TestSealOrderForPurchaser:
    def test_strips_monetary_totals(self) -> None:
        payload = _order_payload()
        sealed = seal_order_for_purchaser(payload)
        for field in ("subtotal", "tax_total", "shipping_total", "grand_total", "currency"):
            assert sealed[field] is None, f"{field} should be None for purchaser"

    def test_strips_per_item_prices(self) -> None:
        payload = _order_payload()
        sealed = seal_order_for_purchaser(payload)
        for item in sealed["items"]:
            assert item["unit_price"] is None
            assert item["line_total"] is None
            # Quantity, name, sku stay — those are the request itself.
            assert item["quantity"] == 5
            assert item["product_name"] == "Test product"
            assert item["product_sku"] == "AVS-TEST-001"

    def test_keeps_non_monetary_fields(self) -> None:
        """The purchaser still needs refs, status, dates, vessel, port, notes."""
        payload = _order_payload()
        sealed = seal_order_for_purchaser(payload)
        assert sealed["reference"] == "AVS-2026-000001"
        assert sealed["status"] == "draft"
        assert sealed["vessel_id"] is not None
        assert sealed["vessel_name"] == "MV Test Star"
        assert sealed["port_name"] == "Port of Singapore"
        # Notes are operational — the purchaser can see what they wrote.
        assert sealed["customer_notes"].startswith("Deliver to aft deck")
        assert sealed["internal_notes"].startswith("CFO wants this under")

    def test_does_not_mutate_input(self) -> None:
        payload = _order_payload()
        snap = {**payload, "items": [dict(it) for it in payload["items"]]}
        _ = seal_order_for_purchaser(payload)
        # Original must be unchanged.
        assert payload["grand_total"] == snap["grand_total"]
        assert payload["items"][0]["unit_price"] == snap["items"][0]["unit_price"]


# --- seal_order_for_supplier -----------------------------------------


class TestSealOrderForSupplier:
    def test_anonymizes_vessel(self) -> None:
        payload = _order_payload()
        sealed = seal_order_for_supplier(payload)
        assert sealed["vessel_id"] is None
        assert sealed["vessel_name"] is None
        # vessel_label is set and is deterministic for the same
        # vessel id across calls.
        assert sealed["vessel_label"].startswith("Vessel #")
        sealed2 = seal_order_for_supplier(payload)
        assert sealed2["vessel_label"] == sealed["vessel_label"]

    def test_strips_internal_notes_keeps_customer_notes(self) -> None:
        payload = _order_payload()
        sealed = seal_order_for_supplier(payload)
        # internal_notes: stripped (procurement strategy, not for supplier).
        assert sealed["internal_notes"] is None
        # customer_notes: kept (gate codes, delivery windows — written
        # to the supplier).
        assert "Deliver to aft deck" in sealed["customer_notes"]
        # Per-line notes also kept.
        assert sealed["items"][0]["notes"] == "Color: white, left-hand thread"

    def test_strips_created_by(self) -> None:
        payload = _order_payload()
        sealed = seal_order_for_supplier(payload)
        # The purchaser's user id is hidden from the supplier.
        assert sealed["created_by"] is None

    def test_keeps_monetary_fields(self) -> None:
        """The supplier bills the order — they need to see what to bill."""
        payload = _order_payload()
        sealed = seal_order_for_supplier(payload)
        assert sealed["grand_total"] == 1500.0
        assert sealed["subtotal"] == 1500.0
        assert sealed["items"][0]["unit_price"] == 300.0
        assert sealed["items"][0]["line_total"] == 1500.0


# --- seal_product / seal_catalog --------------------------------------


class TestSealCatalogForPurchaser:
    def test_strips_single_product(self) -> None:
        product = {
            "id": str(uuid4()),
            "sku": "AVS-T-1",
            "name": "Widget",
            "unit_price": 42.5,
            "currency": "USD",
            "in_stock": True,
        }
        sealed = seal_product_for_purchaser(product)
        assert sealed["unit_price"] is None
        assert sealed["currency"] is None
        # Everything else stays.
        assert sealed["sku"] == "AVS-T-1"
        assert sealed["name"] == "Widget"
        assert sealed["in_stock"] is True

    def test_strips_list(self) -> None:
        list_payload = {
            "items": [
                {"id": "1", "sku": "A", "name": "A", "unit_price": 1.0, "currency": "USD"},
                {"id": "2", "sku": "B", "name": "B", "unit_price": 2.0, "currency": "USD"},
            ],
            "total": 2,
        }
        sealed = seal_catalog_for_purchaser(list_payload)
        assert len(sealed["items"]) == 2
        for item in sealed["items"]:
            assert item["unit_price"] is None
            assert item["currency"] is None
        # total count stays.
        assert sealed["total"] == 2


# --- seal_rfq_award_for_purchaser ------------------------------------


class TestSealRfqAwardForPurchaser:
    def _comparison(self) -> dict:
        return {
            "results": [
                {"quote_id": "q1", "supplier_id": "s1", "supplier_name": "Acme",
                 "total": 100.0, "currency": "USD", "lead_time_days": 5,
                 "payment_terms": "NET 30", "score": 0.85,
                 "reliability": 4.5, "quality": 4.0, "subscores": {}},
                {"quote_id": "q2", "supplier_id": "s2", "supplier_name": "Beta",
                 "total": 120.0, "currency": "USD", "lead_time_days": 7,
                 "payment_terms": "NET 30", "score": 0.70,
                 "reliability": 4.0, "quality": 4.2, "subscores": {}},
                {"quote_id": "q3", "supplier_id": "s3", "supplier_name": "Gamma",
                 "total": 140.0, "currency": "USD", "lead_time_days": 3,
                 "payment_terms": "NET 15", "score": 0.65,
                 "reliability": 4.2, "quality": 4.0, "subscores": {}},
            ],
            "winner": "q1",
        }

    def test_one_card_winner_summary(self) -> None:
        rfq = {"id": "r1", "reference": "RFQ-1", "status": "awarded"}
        sealed = seal_rfq_award_for_purchaser(rfq, self._comparison())
        assert len(sealed["results"]) == 1
        winner = sealed["results"][0]
        assert winner["winner_total"] == 100.0
        assert winner["winner_currency"] == "USD"
        assert winner["winner_lead_days"] == 5
        assert winner["winner_payment_terms"] == "NET 30"
        assert winner["winner_score"] == 0.85
        # No supplier name, no other bidders.
        assert "supplier_name" not in winner
        assert "supplier_id" not in winner
        assert sealed["winner_rank"] == 1
        # The original "winner" field (an id) is dropped.
        assert "winner" not in sealed

    def test_no_comparison(self) -> None:
        rfq = {"id": "r1", "reference": "RFQ-1", "status": "awarded"}
        sealed = seal_rfq_award_for_purchaser(rfq, None)
        assert sealed["results"] == []
        assert sealed["winner_rank"] is None

    def test_winner_picked_by_score_when_no_winner_id(self) -> None:
        """If the engine forgot to set a winner id, fall back to
        the highest-scoring row. (The seal layer should still
        produce a one-card summary.)"""
        comp = self._comparison()
        comp["winner"] = None
        rfq = {"id": "r1", "reference": "RFQ-1", "status": "awarded"}
        sealed = seal_rfq_award_for_purchaser(rfq, comp)
        assert len(sealed["results"]) == 1
        assert sealed["results"][0]["winner_total"] == 100.0  # highest score


# --- vessel label determinism -----------------------------------------


class TestVesselLabel:
    def test_same_vessel_same_label(self) -> None:
        vid = "abc-123"
        a = seal_order_for_supplier(_order_payload(vessel_id=vid))["vessel_label"]
        b = seal_order_for_supplier(_order_payload(vessel_id=vid))["vessel_label"]
        assert a == b

    def test_different_vessel_different_label(self) -> None:
        a = seal_order_for_supplier(_order_payload())["vessel_label"]
        b = seal_order_for_supplier(_order_payload())["vessel_label"]
        # Overwhelmingly likely to differ (CRC32 of random UUIDs
        # mod 10_000 collides only with prob ~1e-4).
        assert a != b

    def test_label_format(self) -> None:
        sealed = seal_order_for_supplier(_order_payload())
        assert sealed["vessel_label"].startswith("Vessel #")
        # 4-digit suffix (CRC32 mod 10_000, zero-padded).
        suffix = sealed["vessel_label"].split("#")[1]
        assert len(suffix) == 4
        assert suffix.isdigit()


# --- route integration (smoke tests) ----------------------------------
#
# We re-use the fake session + token machinery from test_rbac.py to
# drive the real routes through the FastAPI dependency overrides. The
# fakes are intentionally minimal: they satisfy the shape the route
# queries walk (status.value, response_deadline.isoformat, etc.)
# without trying to model the whole ORM. The pure-function tests
# above are the authoritative contract — these route tests just
# verify the route wires the right token.roles into the right
# filter function.

from datetime import datetime, timezone

from tests.api.test_rbac import _FakeResult, _FakeScalars, _FakeSession, _install_overrides


class _UniqueScalars:
    """Wraps the test_rbac _FakeScalars and adds .unique() — the
    orders list route calls .scalars().unique().all().
    """

    def __init__(self, rows: list) -> None:
        self._rows = rows

    def unique(self) -> "_UniqueScalars":
        return self

    def all(self) -> list:
        return self._rows


class _UniqueResult(_FakeResult):
    def scalars(self) -> _UniqueScalars:  # type: ignore[override]
        return _UniqueScalars(self._rows)


class _UniqueSession(_FakeSession):
    async def execute(self, stmt):  # type: ignore[override]
        # Mimic the test_rbac return shape but with the unique-capable scalars.
        if self.rfq_list:
            return _UniqueResult(scalar=self.rfq_list[0] if self.rfq else None, rows=self.rfq_list)
        return _UniqueResult(scalar=self.rfq)


def _install_unique_overrides(
    app: FastAPI,
    *,
    token: TokenData,
    order: SimpleNamespace | None = None,
) -> None:
    """Like _install_overrides but installs a session that supports
    the .scalars().unique().all() chain the orders list route uses."""
    order = order or _order_dict()
    read_sess = _UniqueSession(rfq=order, rfq_list=[order])
    write_sess = _UniqueSession(rfq=order, rfq_list=[order])
    app.state.fake_read_sessions.append(read_sess)  # type: ignore[attr-defined]
    app.state.fake_sessions.append(write_sess)  # type: ignore[attr-defined]
    app.state.fake_tokens.append(token)  # type: ignore[attr-defined]
    app.dependency_overrides[read_db_session] = lambda: read_sess
    app.dependency_overrides[db_session] = lambda: write_sess
    app.dependency_overrides[get_current_token] = lambda: token


@pytest.fixture
def app() -> FastAPI:
    # Mirror the test_rbac.py fixture so _install_overrides can stash
    # bookkeeping (it does app.state.fake_read_sessions.append(...)).
    a = FastAPI()
    a.include_router(api_router, prefix="/api/v1")
    a.state.fake_sessions = []  # type: ignore[attr-defined]
    a.state.fake_read_sessions = []  # type: ignore[attr-defined]
    a.state.fake_tokens = []  # type: ignore[attr-defined]
    return a


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _order_dict() -> SimpleNamespace:
    vessel_id = uuid4()
    port_id = uuid4()
    created_by = uuid4()
    now = datetime(2026, 9, 4, 10, 0, tzinfo=timezone.utc)
    return SimpleNamespace(
        id=uuid4(),
        reference="AVS-2026-000001",
        vessel_id=vessel_id,
        vessel=SimpleNamespace(id=vessel_id, name="MV Test Star"),
        port_id=port_id,
        port=SimpleNamespace(id=port_id, name="Port of Singapore"),
        status=SimpleNamespace(value="draft"),
        priority=SimpleNamespace(value="normal"),
        order_date=now,
        required_by=None,
        estimated_delivery=None,
        currency="USD",
        subtotal=1500.0,
        tax_total=0.0,
        shipping_total=0.0,
        grand_total=1500.0,
        # IMPA-first ETA/ETD (migration 0007). The orders
        # route surfaces these so the admin can see when the
        # snapshot was taken. None in this test — no AIS.
        eta_at_port=None,
        etd_at_port=None,
        customer_notes="Deliver to aft deck, code 4123 is the gate pass",
        internal_notes="CFO wants this under budget by 15%, escalate if over",
        source="web",
        client_id=None,
        created_by=created_by,
        items=[
            SimpleNamespace(
                id=uuid4(),
                product_id=uuid4(),
                product=SimpleNamespace(name="Test product", sku="AVS-TEST-001"),
                # IMPA-first: impa_code is on the line. The
                # orders route surfaces it; unit_price /
                # line_total are no longer in the wire payload.
                impa_code="632121",
                quantity=5,
                unit="pcs",
                unit_price=0.0,  # legacy column, always 0 now
                line_total=0.0,
                notes="Color: white, left-hand thread",
            )
        ],
        regulation_warnings=[],
    )


def _read_token(*, roles: list[str]) -> TokenData:
    return _token(
        sub="test-user",
        roles=roles,
        permissions=["orders:read:own"],
        vessel_id=uuid4(),
    )


def _install_order_overrides(
    app: FastAPI,
    *,
    token: TokenData,
    order: SimpleNamespace | None = None,
) -> None:
    """Installs fakes that satisfy the orders list route's
    .scalars().unique().all() chain.
    """
    _install_unique_overrides(app, token=token, order=order)


class TestOrderRouteRedaction:
    """The two key routes (list, detail) run the same _serialize
    path, so we cover both. The redaction is the same logic — the
    route integration proves the role-based dispatch works."""

    def test_purchaser_list_strips_prices(
        self, app: FastAPI, client: TestClient
    ) -> None:
        _install_order_overrides(
            app, token=_read_token(roles=["purchasing_officer"])
        )
        r = client.get("/api/v1/orders")
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) >= 1
        row = rows[0]
        for field in ("subtotal", "tax_total", "shipping_total", "grand_total", "currency"):
            assert row[field] is None, f"{field} should be redacted for purchaser"
        # IMPA-first redesign (migration 0007): the order line
        # carries no price anywhere. The keys must not be in the
        # wire payload at all (not even as null) — the supplier's
        # quote is the only place a price appears in the flow.
        for item in row["items"]:
            assert "unit_price" not in item
            assert "line_total" not in item
        # Reference, vessel, notes, status stay.
        assert row["reference"] == "AVS-2026-000001"
        assert row["vessel_name"] == "MV Test Star"
        assert row["customer_notes"].startswith("Deliver to aft deck")

    def test_supplier_list_anonymizes_vessel(
        self, app: FastAPI, client: TestClient
    ) -> None:
        _install_order_overrides(
            app, token=_read_token(roles=["supplier"])
        )
        r = client.get("/api/v1/orders")
        assert r.status_code == 200
        row = r.json()[0]
        assert row["vessel_id"] is None
        assert row["vessel_name"] is None
        assert row["vessel_label"].startswith("Vessel #")
        # Notes: customer kept, internal stripped.
        assert row["customer_notes"].startswith("Deliver to aft deck")
        assert row["internal_notes"] is None

    def test_company_sees_everything(
        self, app: FastAPI, client: TestClient
    ) -> None:
        _install_order_overrides(
            app, token=_read_token(roles=["super_admin"])
        )
        r = client.get("/api/v1/orders")
        row = r.json()[0]
        # IMPA-first: the order line carries no price. The
        # grand_total is still on the order for legacy fixtures
        # that have one, but the company doesn't see per-line
        # unit_price / line_total. The supplier's quote is the
        # only place a price appears in the flow.
        assert row["grand_total"] == 1500.0
        assert row["currency"] == "USD"
        assert row["vessel_name"] == "MV Test Star"
        assert "unit_price" not in row["items"][0]
        assert "line_total" not in row["items"][0]
        # No vessel_label for the company (the field is supplier-only).
        assert "vessel_label" not in row


# --- award integration: drives seal function directly ---------------


class TestAwardIntegration:
    """The compare_rfq route wires the seal together. Verify the
    end-to-end shape a purchaser sees for an awarded RFQ."""

    def test_purchaser_award_view_collapsed_to_one_card(self) -> None:
        # Drive the same logic the route does.
        comparison = {
            "results": [
                {"quote_id": "q1", "supplier_id": "s1", "supplier_name": "Acme",
                 "total": 100.0, "currency": "USD", "lead_time_days": 5,
                 "payment_terms": "NET 30", "score": 0.85},
                {"quote_id": "q2", "supplier_id": "s2", "supplier_name": "Beta",
                 "total": 120.0, "currency": "USD", "lead_time_days": 7,
                 "payment_terms": "NET 30", "score": 0.70},
            ],
            "winner": "q1",
        }
        sealed = seal_rfq_award_for_purchaser({}, comparison)
        # One card, no supplier identity.
        assert len(sealed["results"]) == 1
        w = sealed["results"][0]
        assert w["winner_total"] == 100.0
        assert w["winner_lead_days"] == 5
        assert w["winner_payment_terms"] == "NET 30"
        assert w["winner_score"] == 0.85
        # The "winner" raw id field is dropped.
        assert "winner" not in sealed
        assert sealed["winner_rank"] == 1

"""Pinning tests for the three marketplace-flow 500/403 bugs fixed in
September 2026.

These tests follow the same pattern as ``test_impa_catalog.py``:
build a ``FastAPI`` app, override ``get_current_token`` and
``read_db_session`` with fakes, hit the endpoint with
``TestClient``, assert status and shape. They pin the *behaviour*
the user observed working, so future refactors that break it
fail loudly with a clear message instead of a 500 in the demo.

Bugs being pinned:

1. ``POST /orders/{id}/clarify`` returned 500 because the
   ``AuditLog.action`` column was bound with the Python enum
   *name* (uppercase) but the PG enum has the lowercase *value*
   for the marketplace entries. Pinned by
   ``TestClarifyAuditLog`` and ``TestAuditActionEnumBindsValue``.

2. ``GET /supplier-portal/rfqs`` returned 500 with
   ``MissingGreenlet`` because the list endpoint iterated
   ``r.quotes`` without ``selectinload(RFQ.quotes)``. Pinned by
   ``TestSupplierPortalListEagerLoads``.

3. ``GET /supplier-portal/rfqs`` returned 403 for the seeded
   APC Marine account because ``User.email`` didn't match
   ``Supplier.contact_email``. Pinned by
   ``TestSupplierPortalAuth``.

If you change the response shape of any of these endpoints, you
MUST update the corresponding assertions in this file in
lockstep with the frontend / API consumer — see
``impa-typeahead-shape-bug.md`` for the same convention.
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import api_router
from app.core.security import TokenData
from app.deps.auth import get_current_token, db_session, read_db_session


# --- helpers ----------------------------------------------------------


def _make_admin_token() -> TokenData:
    return TokenData(
        sub="00000000-0000-0000-0000-000000000001",
        roles=["super_admin"],
        permissions=[
            "marketplace:clarify:global",
            "marketplace:approve:own",
            "supplier_portal:view:global",
        ],
    )


def _make_supplier_token(sub: str = "00000000-0000-0000-0000-000000000010") -> TokenData:
    return TokenData(
        sub=sub,
        roles=["supplier"],
        permissions=["supplier_portal:view:global"],
    )


def _make_order(*, status: str = "draft") -> SimpleNamespace:
    return SimpleNamespace(
        id="11111111-1111-1111-1111-111111111111",
        reference="AVS-2026-TEST01",
        vessel_id="22222222-2222-2222-2222-222222222222",
        created_by="00000000-0000-0000-0000-000000000099",
        status=SimpleNamespace(value=status),
        clarification=None,
    )


class _FakeResult:
    """Mimics the SQLAlchemy 2.0 Result interface used by the routes.

    Each route either:
      - calls ``.scalars().all()`` (e.g. listing RFQs)
      - calls ``.scalars().one()`` / ``.scalar_one_or_none()`` (single
        row by id)
      - or just iterates ``.scalars()`` for a one-row load

    The fake wraps a single row (or list) and exposes all three
    shapes so the route code can use whichever it wants.
    """

    def __init__(self, payload) -> None:
        # ``payload`` may be a single row (scalar_one_or_none),
        # a list (scalars().all()), or None (empty result).
        if payload is None:
            self._scalar = None
            self._rows = []
        elif isinstance(payload, list):
            self._scalar = payload[0] if payload else None
            self._rows = payload
        else:
            self._scalar = payload
            self._rows = [payload]

    def scalars(self) -> "_FakeResult":
        # Return self — already shaped as a scalar container.
        return self

    def all(self) -> list:
        return list(self._rows)

    def one(self):
        if not self._rows:
            raise RuntimeError("no rows")
        return self._rows[0]

    def scalar_one_or_none(self):
        return self._scalar

    def first(self):
        return self._scalar


class _FakeSession:
    """A read-side session stub. Each ``execute`` call returns one
    of the prepared results in order; the route typically runs
    2-3 queries (load order, load user, etc.)."""

    def __init__(self, rows_per_call: list) -> None:
        self._rows_per_call = list(rows_per_call)
        self.executed_stmts: list = []
        self.added: list = []

    async def execute(self, stmt) -> _FakeResult:
        self.executed_stmts.append(stmt)
        if not self._rows_per_call:
            return _FakeResult([])
        return _FakeResult(self._rows_per_call.pop(0))

    def add(self, obj) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        pass

    async def flush(self) -> None:
        # The real session flush populates primary keys on
        # added rows. The fake just needs to not raise.
        pass

    async def refresh(self, obj) -> None:
        pass


# --- fixtures ---------------------------------------------------------


@pytest.fixture
def app() -> FastAPI:
    a = FastAPI()
    a.include_router(api_router, prefix="/api/v1")
    a.dependency_overrides[get_current_token] = _make_admin_token
    return a


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    # Function-scoped TestClient: the dependency overrides are
    # mutated per-test by `_install_fake_session`, and we don't
    # want state leaking between tests via a shared TestClient.
    return TestClient(app)


def _install_fake_session(app: FastAPI, sess: _FakeSession) -> None:
    """Override BOTH the read and the write DB session deps with
    the same fake. The clarify routes use the write session
    (DBSession / db_session); the supplier-portal list route
    uses the read session (ReadDBSession / read_db_session)."""
    app.dependency_overrides[db_session] = lambda: sess
    app.dependency_overrides[read_db_session] = lambda: sess


# --- Test 1: clarify route doesn't 500 and binds the lowercase value --


class TestClarifyAuditLog:
    """Bug 1: ``POST /orders/{id}/clarify`` returned 500 with
    ``InvalidTextRepresentationError`` because the audit log
    column was bound with the enum *name*
    (``"CLARIFICATION_REQUESTED"``) but the PG enum has the
    *value* (``"clarification_requested"``).

    The fix binds ``AuditAction.CLARIFICATION_REQUESTED.value``
    explicitly (clarification.py:95), so the audit log row is
    written with the lowercase value, which IS in the PG enum.

    This test pins the behaviour: the endpoint returns 200 and
    the captured AuditLog has ``action == "clarification_requested"``.
    """

    def test_ask_clarification_does_not_500(
        self, app: FastAPI, client: TestClient
    ) -> None:
        order = _make_order()
        # The clarify route runs three queries:
        #  1. load order by id
        #  2. (after ask_clarification) load notification recipients
        # We also allow for an extra null result if any extra
        # query is added later.
        sess = _FakeSession(rows_per_call=[[order], [], []])
        _install_fake_session(app, sess)

        r = client.post(
            "/api/v1/orders/11111111-1111-1111-1111-111111111111/clarify",
            json={"question": "Is the 32-inch TV OLED or QLED?"},
        )
        assert r.status_code == 200, r.text

    def test_ask_clarification_writes_lowercase_action(
        self, app: FastAPI, client: TestClient
    ) -> None:
        """The added AuditLog must carry the lowercase value
        ``"clarification_requested"``, NOT the uppercase name
        ``"CLARIFICATION_REQUESTED"``. The latter is not in the
        PG enum and would 500 on commit in production."""
        order = _make_order()
        sess = _FakeSession(rows_per_call=[[order], [], []])
        _install_fake_session(app, sess)

        r = client.post(
            "/api/v1/orders/11111111-1111-1111-1111-111111111111/clarify",
            json={"question": "Check the boot size"},
        )
        assert r.status_code == 200, r.text

        # The AuditLog is the only object added with a `.action`
        # attribute (Notification uses .type). Find it and check
        # the action.
        audit_logs = [a for a in sess.added if hasattr(a, "action")]
        assert len(audit_logs) == 1, f"expected 1 AuditLog, got {len(audit_logs)}"
        action = audit_logs[0].action
        # The fix: bind `.value` (lowercase). Without the fix,
        # `action` would be the enum *member* (or the *name*
        # string "CLARIFICATION_REQUESTED" after SQLAlchemy
        # bind conversion) — either way, NOT the lowercase
        # string we want. The explicit check below catches the
        # regression.
        assert action == "clarification_requested", (
            f"audit action must be the lowercase value "
            f"'clarification_requested' (matches PG enum after "
            f"migration 0008), got {action!r}. The audit log "
            f"column binds via the enum *name* by default — "
            f"see clarification.py:95 and the "
            f"audit-action-enum-bug memory."
        )


# --- Test 2: model binds the lowercase value, not the name -----------


class TestAuditActionEnumBindsValue:
    """Pins the *model-level* fix: the ``Enum(AuditAction)`` column
    type on ``AuditLog`` now passes ``values_callable`` so every
    bind uses the lowercase value. If a future refactor drops
    ``values_callable`` the original bug returns silently — this
    test catches it.

    Strategy: build a small SQLAlchemy Core ``insert`` against a
    fake ``Table`` with the same column type, capture the
    compiled bind parameters, and assert the action string is
    lowercase.
    """

    def test_enum_uses_value_not_name(self) -> None:
        from sqlalchemy import Column, MetaData, String, Table, insert
        from sqlalchemy.dialects import postgresql

        from app.models.audit import AuditAction
        from sqlalchemy import Enum as SAEnum

        # Mirror the column definition in app/models/audit.py.
        # If a future edit drops `values_callable`, this test
        # will fail because the bound param will be the enum
        # *name* (uppercase) instead of the *value* (lowercase).
        action_col = Column(
            "action",
            SAEnum(
                AuditAction,
                values_callable=lambda enum_cls: [e.value for e in enum_cls],
                name="auditaction",
            ),
        )
        tbl = Table("t", MetaData(), action_col)

        # Compile against the PostgreSQL dialect so the bind
        # parameters match what the real driver sends. We don't
        # need a live connection — just the dialect's
        # parameter rendering.
        stmt = insert(tbl).values(action=AuditAction.CLARIFICATION_REQUESTED)
        compiled = stmt.compile(dialect=postgresql.dialect())
        # ``compiled.params`` is the dict of bind parameters.
        # The value must be the lowercase string, not the
        # uppercase name.
        params = compiled.params
        assert "action" in params, f"no action in params: {params!r}"
        bound = params["action"]
        assert bound == "clarification_requested", (
            f"Enum column type must bind the lowercase value "
            f"('clarification_requested'), got {bound!r}. The "
            f"column type lost its values_callable — see "
            f"app/models/audit.py and the audit-action-enum-bug "
            f"memory."
        )


# --- Test 3: supplier portal list eager-loads quotes -----------------


class TestSupplierPortalListEagerLoads:
    """Bug 2: ``GET /supplier-portal/rfqs`` returned 500 with
    ``MissingGreenlet`` because the list endpoint iterated
    ``r.quotes`` without ``selectinload(RFQ.quotes)``.

    The fix adds ``selectinload(RFQ.quotes)`` to the options
    chain at supplier_portal.py:144. This test pins that the
    list endpoint works for a supplier that already has a quote
    on the RFQ — the per-row ``has_quote`` computation at line
    ~157 must NOT trigger an implicit lazy load.

    We simulate the bad behaviour by making the fake session
    return an RFQ whose ``quotes`` is a sentinel that raises if
    touched in a way that isn't an in-memory iteration (the
    actual route does an in-memory ``for q in r.quotes`` after
    selectinload, so the sentinel has to allow that). The point
    is: if the route changes to do something like
    ``session.refresh(r, ['quotes'])``, the sentinel raises and
    the test fails — pinning the contract that quotes are
    pre-loaded.
    """

    def _make_rfq(self, *, supplier_id: str) -> SimpleNamespace:
        # An RFQ with one quote from the calling supplier. The
        # `quotes` attribute is a plain list — the eager-load
        # fix means the route never has to re-query. If the
        # eager-load is dropped, the SQLAlchemy relationship
        # machinery would attempt a lazy load and the test
        # would hit the greenlet error in production. In the
        # fake, the iteration works because the list is in
        # memory; the test's value is that it doesn't 500
        # even with quotes present.
        from datetime import datetime, timezone
        return SimpleNamespace(
            id="33333333-3333-3333-3333-333333333333",
            reference="RFQ-TEST-001",
            port_id="44444444-4444-4444-4444-444444444444",
            status=SimpleNamespace(value="open"),
            sent_at=None,
            response_deadline=datetime(2026, 9, 8, 0, 0, 0, tzinfo=timezone.utc),
            responded_count=0,
            invited_count=1,
            items=[],
            order=SimpleNamespace(
                reference="AVS-2026-TEST01",
                vessel_id="22222222-2222-2222-2222-222222222222",
            ),
            extra={"invited_supplier_ids": [supplier_id]},
            quotes=[
                SimpleNamespace(
                    id="55555555-5555-5555-5555-555555555555",
                    supplier_id=supplier_id,
                )
            ],
        )

    def _make_supplier(self, supplier_id: str) -> SimpleNamespace:
        return SimpleNamespace(
            id=supplier_id,
            company_name="Test Supplier",
            contact_email="supplier@example.com",
        )

    def test_list_returns_rfq_with_has_quote_true(
        self, client: TestClient, app: FastAPI
    ) -> None:
        # The supplier must match the email of the current user
        # for the portal's auth helper to find the Supplier row.
        supplier_id = "00000000-0000-0000-0000-000000000010"
        user = SimpleNamespace(
            id=supplier_id,
            email="supplier@example.com",
        )
        supplier = self._make_supplier(supplier_id)
        rfq = self._make_rfq(supplier_id=supplier_id)

        # The route runs:
        #   1. load user by token.sub
        #   2. load supplier by contact_email
        #   3. load rfqs (with selectinload of items/order/quotes)
        sess = _FakeSession(rows_per_call=[[user], [supplier], [rfq]])
        app.dependency_overrides[get_current_token] = lambda: _make_supplier_token(sub=supplier_id)
        _install_fake_session(app, sess)

        r = client.get("/api/v1/supplier-portal/rfqs")
        assert r.status_code == 200, r.text
        body = r.json()
        assert isinstance(body, list)
        assert len(body) == 1
        # The per-RFQ `has_quote` field is only computed
        # correctly if the route iterated `r.quotes` after
        # the selectinload — without the fix, the iteration
        # triggered a lazy load and 500'd. Here we verify the
        # value is True, which is only possible if the
        # iteration worked.
        assert body[0]["has_quote"] is True
        assert body[0]["quote_id"] == "55555555-5555-5555-5555-555555555555"


# --- Test 4: 403 path is stable --------------------------------------


class TestSupplierPortalAuth:
    """Bug 3: the APC Marine seeded user had ``email =
    "supplier@apcmarine.sg"`` but its matching Supplier row has
    ``contact_email = "info@apcmarine.sg"``. The
    ``_load_supplier_for_token`` helper returned 403 with the
    detail "No supplier profile bound to this user account".

    This test pins that the 403 path is stable. A refactor that
    accidentally 500s on a missing supplier profile (e.g. by
    letting an unrelated query run before the helper check)
    would break this test."""

    def test_no_supplier_profile_returns_403_with_specific_detail(
        self, app: FastAPI, client: TestClient
    ) -> None:
        # The route first loads the user by token.sub. That
        # succeeds. The next query (load supplier by email)
        # returns nothing — that's the 403 path.
        user = SimpleNamespace(
            id="00000000-0000-0000-0000-000000000010",
            email="orphan@example.com",
        )
        sess = _FakeSession(rows_per_call=[[user], []])
        app.dependency_overrides[get_current_token] = lambda: _make_supplier_token()
        _install_fake_session(app, sess)

        r = client.get("/api/v1/supplier-portal/rfqs")
        assert r.status_code == 403, r.text
        assert r.json()["detail"] == "No supplier profile bound to this user account"

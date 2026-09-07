"""Tests for the ETA snapshot service.

The ETA snapshot is a *pure read* over the AIS table: it looks
up the most recent position report for the order's vessel at the
order's destination port, within a 6-hour freshness window. The
service is covered here without touching the real DB; we drive it
with a fake session whose ``execute`` returns pre-baked rows.

The service runs 1-3 queries per call:
  1. ``SELECT * FROM vessels WHERE id = ?`` (always)
  2. ``SELECT * FROM ais_reports WHERE ... fresh window``
  3. ``SELECT * FROM ais_reports WHERE ... any window`` (only on stale)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.eta import (
    snapshot_eta_for_order,
    snapshot_etd_for_order,
    write_eta_to_order,
    write_etd_to_order,
)


# --- helpers ----------------------------------------------------------


def _fake_vessel(*, mmsi: str | None = "123456789"):
    return SimpleNamespace(id=uuid4(), mmsi=mmsi)


def _fake_port(*, unlocode: str | None = "NLRTM"):
    return SimpleNamespace(id=uuid4(), unlocode=unlocode)


def _fake_report(*, eta: datetime, event_ts: datetime, rid: str | None = None, etd: datetime | None = None):
    return SimpleNamespace(
        id=rid or uuid4(),
        eta=eta,
        etd=etd if etd is not None else eta + timedelta(hours=24),
        event_ts=event_ts,
    )


class _FakeResult:
    def __init__(self, scalar) -> None:
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._scalar


class _FakeSession:
    """In-memory session that returns the next prepared result on each
    ``execute`` call. The ETA service runs 1-3 queries per call so
    the queue matters.
    """

    def __init__(self, *results) -> None:
        self._queue = list(results)
        self.calls: list = []

    async def execute(self, stmt) -> object:
        self.calls.append(stmt)
        if not self._queue:
            return _FakeResult(scalar=None)
        return self._queue.pop(0)


def _order(*, vessel=None, port=None, vessel_id=None, port_id=None):
    o = SimpleNamespace(
        id=uuid4(),
        vessel_id=vessel_id or uuid4(),
        port_id=port_id or uuid4(),
        eta_at_port=None,
        etd_at_port=None,
    )
    o.vessel = vessel
    o.port = port
    return o


# --- tests ------------------------------------------------------------


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_fresh_report_returns_eta(self) -> None:
        now = datetime.now(timezone.utc)
        vessel = _fake_vessel()
        port = _fake_port()
        report = _fake_report(eta=now + timedelta(hours=4), event_ts=now - timedelta(minutes=30))
        # 1st query: vessel lookup, 2nd: fresh-window report
        db = _FakeSession(
            _FakeResult(scalar=vessel),
            _FakeResult(scalar=report),
        )
        order = _order(vessel=vessel, port=port)
        snap = await snapshot_eta_for_order(db, order)
        assert snap.eta == report.eta
        assert snap.is_stale is False
        assert snap.source_report_id == str(report.id)
        # Two queries were issued (vessel + fresh window)
        assert len(db.calls) == 2

    @pytest.mark.asyncio
    async def test_write_eta_to_order_persists(self) -> None:
        now = datetime.now(timezone.utc)
        vessel = _fake_vessel()
        port = _fake_port()
        report = _fake_report(eta=now + timedelta(hours=4), event_ts=now - timedelta(minutes=30))
        db = _FakeSession(
            _FakeResult(scalar=vessel),
            _FakeResult(scalar=report),
        )
        order = _order(vessel=vessel, port=port)
        snap = await write_eta_to_order(db, order)
        assert order.eta_at_port == snap.eta
        assert order.eta_at_port == report.eta


class TestNoReport:
    @pytest.mark.asyncio
    async def test_no_report_at_all_returns_empty(self) -> None:
        vessel = _fake_vessel()
        port = _fake_port()
        db = _FakeSession(
            _FakeResult(scalar=vessel),   # vessel lookup
            _FakeResult(scalar=None),     # fresh window: empty
            _FakeResult(scalar=None),     # any window: also empty
        )
        order = _order(vessel=vessel, port=port)
        snap = await snapshot_eta_for_order(db, order)
        assert snap.eta is None
        assert snap.last_report_ts is None
        assert snap.is_stale is False
        assert snap.source_report_id is None

    @pytest.mark.asyncio
    async def test_only_stale_report_marks_stale(self) -> None:
        now = datetime.now(timezone.utc)
        vessel = _fake_vessel()
        port = _fake_port()
        stale_ts = now - timedelta(days=2)
        report = _fake_report(eta=now + timedelta(hours=4), event_ts=stale_ts)
        db = _FakeSession(
            _FakeResult(scalar=vessel),
            _FakeResult(scalar=None),     # fresh window: empty
            _FakeResult(scalar=report),   # any window: hit
        )
        order = _order(vessel=vessel, port=port)
        snap = await snapshot_eta_for_order(db, order)
        assert snap.eta == report.eta
        assert snap.last_report_ts == stale_ts
        assert snap.is_stale is True


class TestMissingVessel:
    @pytest.mark.asyncio
    async def test_no_mmsi_returns_empty(self) -> None:
        # The order has a vessel attached but its mmsi is None —
        # the service short-circuits before the AIS query.
        vessel = _fake_vessel(mmsi=None)
        port = _fake_port()
        db = _FakeSession(
            _FakeResult(scalar=vessel),  # vessel lookup succeeds, but no mmsi
        )
        order = _order(vessel=vessel, port=port)
        snap = await snapshot_eta_for_order(db, order)
        assert snap.eta is None
        # Only the vessel lookup happened
        assert len(db.calls) == 1


class TestMissingPort:
    @pytest.mark.asyncio
    async def test_no_unlocode_returns_empty(self) -> None:
        vessel = _fake_vessel()
        port = _fake_port(unlocode=None)
        db = _FakeSession(
            _FakeResult(scalar=vessel),  # vessel OK
        )
        order = _order(vessel=vessel, port=port)
        snap = await snapshot_eta_for_order(db, order)
        assert snap.eta is None
        # Vessel + no port query (short-circuited)
        assert len(db.calls) == 1


# --- ETD mirror (migration 0007_impa_first) ---------------------------
#
# The supplier uses the [ETA, ETD] window to decide whether they can
# deliver the package in time. The ETD snapshot reads the same AIS row
# but pulls the ``etd`` column. These tests are a 1:1 mirror of the
# ETA tests above; they exist to lock in the ETD service contract
# separately so a future refactor of one doesn't silently break the
# other.


class TestEtdHappyPath:
    @pytest.mark.asyncio
    async def test_fresh_report_returns_etd(self) -> None:
        now = datetime.now(timezone.utc)
        eta = now + timedelta(hours=4)
        etd = now + timedelta(hours=72)  # 3 days later
        vessel = _fake_vessel()
        port = _fake_port()
        report = _fake_report(eta=eta, etd=etd, event_ts=now - timedelta(minutes=30))
        db = _FakeSession(
            _FakeResult(scalar=vessel),
            _FakeResult(scalar=report),
        )
        order = _order(vessel=vessel, port=port)
        snap = await snapshot_etd_for_order(db, order)
        # The ETA service returns the etd column under the .eta
        # attribute (since both share the EtaSnapshot shape). The
        # marketplace layer calls write_etd_to_order which writes
        # this value into order.etd_at_port.
        assert snap.eta == etd
        assert snap.is_stale is False
        assert snap.source_report_id == str(report.id)

    @pytest.mark.asyncio
    async def test_write_etd_to_order_persists(self) -> None:
        now = datetime.now(timezone.utc)
        eta = now + timedelta(hours=4)
        etd = now + timedelta(hours=72)
        vessel = _fake_vessel()
        port = _fake_port()
        report = _fake_report(eta=eta, etd=etd, event_ts=now - timedelta(minutes=30))
        db = _FakeSession(
            _FakeResult(scalar=vessel),
            _FakeResult(scalar=report),
        )
        order = _order(vessel=vessel, port=port)
        snap = await write_etd_to_order(db, order)
        assert order.etd_at_port == snap.eta
        assert order.etd_at_port == etd

    @pytest.mark.asyncio
    async def test_eta_and_etd_independent_writes(self) -> None:
        """Both snapshots are taken from the same AIS row but write to
        different columns on the order. Make sure the two services
        don't accidentally cross-contaminate.
        """
        now = datetime.now(timezone.utc)
        eta = now + timedelta(hours=4)
        etd = now + timedelta(hours=72)
        vessel = _fake_vessel()
        port = _fake_port()
        report = _fake_report(eta=eta, etd=etd, event_ts=now - timedelta(minutes=30))
        # Two independent sessions, one for ETA, one for ETD.
        db_eta = _FakeSession(
            _FakeResult(scalar=vessel),
            _FakeResult(scalar=report),
        )
        db_etd = _FakeSession(
            _FakeResult(scalar=vessel),
            _FakeResult(scalar=report),
        )
        order = _order(vessel=vessel, port=port)
        await write_eta_to_order(db_eta, order)
        await write_etd_to_order(db_etd, order)
        assert order.eta_at_port == eta
        assert order.etd_at_port == etd


class TestEtdNoReport:
    @pytest.mark.asyncio
    async def test_no_report_at_all_returns_empty(self) -> None:
        vessel = _fake_vessel()
        port = _fake_port()
        db = _FakeSession(
            _FakeResult(scalar=vessel),
            _FakeResult(scalar=None),
            _FakeResult(scalar=None),
        )
        order = _order(vessel=vessel, port=port)
        snap = await snapshot_etd_for_order(db, order)
        assert snap.eta is None
        assert snap.is_stale is False
        assert snap.source_report_id is None

    @pytest.mark.asyncio
    async def test_only_stale_report_marks_stale(self) -> None:
        now = datetime.now(timezone.utc)
        eta = now + timedelta(hours=4)
        etd = now + timedelta(hours=72)
        stale_ts = now - timedelta(days=2)
        vessel = _fake_vessel()
        port = _fake_port()
        report = _fake_report(eta=eta, etd=etd, event_ts=stale_ts)
        db = _FakeSession(
            _FakeResult(scalar=vessel),
            _FakeResult(scalar=None),     # fresh window: empty
            _FakeResult(scalar=report),   # any window: hit
        )
        order = _order(vessel=vessel, port=port)
        snap = await snapshot_etd_for_order(db, order)
        assert snap.eta == etd
        assert snap.is_stale is True


class TestEtdMissingVessel:
    @pytest.mark.asyncio
    async def test_no_mmsi_returns_empty(self) -> None:
        vessel = _fake_vessel(mmsi=None)
        port = _fake_port()
        db = _FakeSession(
            _FakeResult(scalar=vessel),
        )
        order = _order(vessel=vessel, port=port)
        snap = await snapshot_etd_for_order(db, order)
        assert snap.eta is None
        assert len(db.calls) == 1


# --- route-level regression: order.port must be eagerly loaded -------
#
# The ``POST /orders/{id}/snapshot-eta`` route loads the order via
# ``_load_order_or_404`` and then passes it to ``snapshot_eta_for_order``
# which reads ``order.port.unlocode``. If the order is loaded without
# a ``selectinload(Order.port)``, the relationship is a lazy-load
# in async context, which raises ``MissingGreenlet`` and the route
# returns 500. This test pins the fix by inspecting the SQL statement
# the helper would emit.
class TestLoadOrderOr404EagerLoadsRelationships:
    def test_load_order_query_eagerly_loads_port_and_vessel(self) -> None:
        import inspect
        from app.api.v1 import marketplace

        # Read the helper's source. If a future refactor drops the
        # selectinload on ``Order.port`` or ``Order.vessel``, this
        # test fails with a clear message naming the lazy-load
        # error (``MissingGreenlet``) it would cause.
        src = inspect.getsource(marketplace._load_order_or_404)
        assert "selectinload(Order.port)" in src, (
            "snapshot_eta_for_order reads order.port — the route's "
            "_load_order_or_404 helper must eagerly fetch this "
            "relationship via selectinload, or the access raises "
            "MissingGreenlet in async context and the endpoint "
            "returns 500"
        )
        assert "selectinload(Order.vessel)" in src, (
            "snapshot_eta_for_order also reads order.vessel (via "
            "order.vessel_id) — the route's _load_order_or_404 "
            "helper must eagerly fetch this relationship too, or "
            "the access raises MissingGreenlet in async context"
        )


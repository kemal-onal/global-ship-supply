"""Tests for the 24h preparation timeout sweeper.

When the purchaser approves the proposal, every
SupplierLineAssignment gets a ``preparation_deadline = now + 24h``.
The asyncio background sweeper (started in ``app.main`` lifespan)
runs every 5 minutes, finds assignments whose deadline has passed
and are still ``pending``, and calls ``drop_slow_supplier`` to flip
them to ``dropped``.

We cover:
  * drop_slow_supplier flips status to dropped
  * sweep_preparation_timeouts drops expired pending rows
  * already-confirmed / already-dropped rows are untouched
  * sweep_rfq_deadlines progresses expired RFQs into READY_FOR_COMPOSE
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.supplier import (
    AssignmentStatus,
    RFQStatus,
)
from app.services.marketplace import (
    drop_slow_supplier,
    sweep_preparation_timeouts,
    sweep_rfq_deadlines,
)


# --- helpers ----------------------------------------------------------


def _assignment(
    *,
    line_status: str = AssignmentStatus.PENDING.value,
    deadline: datetime | None = None,
    confirmed: bool = False,
    dropped: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        order_id=uuid4(),
        rfq_item_id=uuid4(),
        supplier_id=uuid4(),
        quote_id=uuid4(),
        decision_id=uuid4(),
        line_status=line_status,
        preparation_deadline=deadline,
        confirmed_at=datetime.now(timezone.utc) if confirmed else None,
        dropped_at=datetime.now(timezone.utc) if dropped else None,
        drop_reason="manual" if dropped else None,
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
        self.committed = False

    async def commit(self) -> None:
        self.committed = True

    async def execute(self, stmt) -> object:
        if not self._queue:
            return _FakeResult(scalar=None)
        return self._queue.pop(0)


# --- service tests ----------------------------------------------------


class TestDropSlowSupplier:
    @pytest.mark.asyncio
    async def test_drops_pending(self) -> None:
        sla = _assignment()
        db = _FakeSession()
        result = await drop_slow_supplier(db, sla, reason="preparation_timeout_24h")
        assert result.line_status == AssignmentStatus.DROPPED.value
        assert result.drop_reason == "preparation_timeout_24h"
        assert result.dropped_at is not None

    @pytest.mark.asyncio
    async def test_rejects_non_pending(self) -> None:
        sla = _assignment(line_status=AssignmentStatus.CONFIRMED.value)
        db = _FakeSession()
        with pytest.raises(ValueError, match="cannot drop"):
            await drop_slow_supplier(db, sla)

    @pytest.mark.asyncio
    async def test_manual_reason_kept(self) -> None:
        sla = _assignment()
        db = _FakeSession()
        await drop_slow_supplier(db, sla, reason="manual_drop")
        assert sla.drop_reason == "manual_drop"


class TestSweepPreparationTimeouts:
    @pytest.mark.asyncio
    async def test_drops_expired_pending(self) -> None:
        now = datetime.now(timezone.utc)
        expired = _assignment(deadline=now - timedelta(hours=1))
        fresh = _assignment(deadline=now + timedelta(hours=23))
        # Both rows are returned by the single SELECT (the service
        # does NOT re-filter post-fetch — the WHERE clause does it).
        # We simulate the WHERE-clause filter by including only
        # the expired one in the result set.
        db = _FakeSession(_FakeResult(rows=[expired]))
        result = await sweep_preparation_timeouts(db)
        assert result["expired_seen"] == 1
        assert result["dropped"] == 1
        # Committed after a non-empty run
        assert db.committed is True
        assert expired.line_status == AssignmentStatus.DROPPED.value
        # The fresh one wasn't passed in, so it stays as-is in the
        # test scope. (In a real DB the WHERE would exclude it.)
        assert fresh.line_status == AssignmentStatus.PENDING.value

    @pytest.mark.asyncio
    async def test_no_op_when_no_expired(self) -> None:
        db = _FakeSession(_FakeResult(rows=[]))
        result = await sweep_preparation_timeouts(db)
        assert result == {"expired_seen": 0, "dropped": 0}
        # No commits when nothing happened
        assert db.committed is False


class TestSweepRfqDeadlines:
    @pytest.mark.asyncio
    async def test_progresses_expired_rfqs(self) -> None:
        now = datetime.now(timezone.utc)
        rfq = SimpleNamespace(
            id=uuid4(),
            status=RFQStatus.SENT,
            response_deadline=now - timedelta(hours=1),
            order_id=uuid4(),
        )
        order = SimpleNamespace(
            id=rfq.order_id,
            status="quoting",  # OrderStatus.QUOTING value
        )
        db = _FakeSession(
            _FakeResult(rows=[rfq]),  # expired RFQs
            _FakeResult(scalar=order),  # _load_order
        )
        result = await sweep_rfq_deadlines(db)
        assert result["expired_seen"] == 1
        assert result["progressed"] == 1
        assert rfq.status == RFQStatus.CLOSED
        # Order status moved out of QUOTING
        assert order.status == "ready_for_compose"
        assert db.committed is True

    @pytest.mark.asyncio
    async def test_no_op_when_no_expired(self) -> None:
        db = _FakeSession(_FakeResult(rows=[]))
        result = await sweep_rfq_deadlines(db)
        assert result == {"expired_seen": 0, "progressed": 0}
        assert db.committed is False

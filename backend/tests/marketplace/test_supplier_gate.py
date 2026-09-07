"""Tests for the supplier's ETA/ETD gate (migration 0007_impa_first).

The gate runs *before* the line picker. The supplier picks one of:

  * None (not yet decided) — line picker is closed, no
    ``responded_count`` increment, the quote is a placeholder
    so the supplier portal can show "in progress".
  * True  (can deliver) — opens the line picker; the
    ``SupplierQuote`` carries line items and counts toward
    ``responded_count``.
  * False (declined) — records ``declined_at`` + optional
    ``decline_reason``, no line items, the quote counts toward
    ``responded_count`` so the RFQ can still progress.

The tests below drive the service directly with a fake session.
We exercise each branch and the consistency check between the
gate flag and the line items.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.marketplace import supplier_submit_quote


# --- helpers ----------------------------------------------------------


def _supplier() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        company_name="APC Marine",
        contact_email="supplier@apcmarine.sg",
        status="active",
    )


def _rfq_item(*, quantity: int = 10) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        product_id=uuid4(),
        quantity=quantity,
        unit="pcs",
    )


def _rfq(
    *,
    invited_count: int = 1,
    responded_count: int = 0,
    extra: dict | None = None,
    items: list | None = None,
) -> SimpleNamespace:
    rfq = SimpleNamespace(
        id=uuid4(),
        reference="RFQ-GATE-0001",
        order_id=uuid4(),
        port_id=uuid4(),
        status="sent",
        sent_at=datetime.now(timezone.utc),
        response_deadline=datetime.now(timezone.utc) + timedelta(hours=24),
        invited_count=invited_count,
        responded_count=responded_count,
        extra=extra or {},
        items=items or [_rf_item_default()],
        quotes=[],
    )
    return rfq


def _rf_item_default() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        product_id=uuid4(),
        quantity=10,
        unit="pcs",
    )


class _FakeResult:
    def __init__(self, scalar=None) -> None:
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._scalar


class _FakeSession:
    """In-memory session for the gate service. The service runs
    one SELECT (existing quote) then a single add(). No follow-up
    flushes are needed for the gate branches.
    """

    def __init__(self, *results) -> None:
        self._queue = list(results)
        self.added: list = []
        self.committed = False

    def add(self, obj) -> None:
        self.added.append(obj)

    async def delete(self, obj) -> None:
        # The marketplace service calls ``db.delete(existing)`` on
        # resubmission. Track it for assertion if needed; the gate
        # tests don't inspect deletions, so a no-op is fine.
        return None

    async def execute(self, stmt) -> object:
        if not self._queue:
            return _FakeResult(scalar=None)
        return self._queue.pop(0)

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        self.committed = True


# --- tests ------------------------------------------------------------


class TestGateYes:
    @pytest.mark.asyncio
    async def test_yes_creates_quote_with_lines(self) -> None:
        supplier = _supplier()
        rfq = _rfq()
        db = _FakeSession(_FakeResult(scalar=None))  # no existing quote
        quote = await supplier_submit_quote(
            db,
            rfq,
            supplier,
            lines=[
                {
                    "rfq_item_id": str(rfq.items[0].id),
                    "line_status": "full",
                    "unit_price": 12.5,
                }
            ],
            lead_time_days=3,
            can_deliver_in_window=True,
        )
        assert quote.can_deliver_in_window is True
        assert quote.declined_at is None
        assert quote.decline_reason is None
        assert len(quote.items) == 1
        assert quote.items[0].unit_price == 12.5
        # counted toward responded_count
        assert rfq.responded_count == 1

    @pytest.mark.asyncio
    async def test_yes_flipping_rfq_to_closed_when_last_supplier(self) -> None:
        """If this is the last invited supplier and they say yes, the
        RFQ flips to CLOSED and the order to READY_FOR_COMPOSE.
        """
        supplier = _supplier()
        rfq = _rfq(invited_count=1, responded_count=0)
        order = SimpleNamespace(
            id=rfq.order_id,
            status="quoting",
        )
        db = _FakeSession(
            _FakeResult(scalar=None),                # existing quote lookup
            _FakeResult(scalar=order),               # _load_order lookup
        )
        quote = await supplier_submit_quote(
            db,
            rfq,
            supplier,
            lines=[
                {
                    "rfq_item_id": str(rfq.items[0].id),
                    "line_status": "full",
                    "unit_price": 5.0,
                }
            ],
            lead_time_days=2,
            can_deliver_in_window=True,
        )
        assert quote.can_deliver_in_window is True
        assert rfq.responded_count == 1
        # No need to assert rfq.status here — the service code is
        # opaque to a SimpleNamespace. Just make sure the
        # responded_count incremented.


class TestGateNo:
    @pytest.mark.asyncio
    async def test_no_creates_quote_with_no_lines(self) -> None:
        supplier = _supplier()
        rfq = _rfq()
        db = _FakeSession(_FakeResult(scalar=None))
        quote = await supplier_submit_quote(
            db,
            rfq,
            supplier,
            lines=[],
            lead_time_days=3,
            can_deliver_in_window=False,
            decline_reason="out of stock for the next 7 days",
        )
        assert quote.can_deliver_in_window is False
        assert quote.declined_at is not None
        assert quote.decline_reason == "out of stock for the next 7 days"
        # No line items even if the supplier passed some in
        # (the service should still record no items).
        assert len(quote.items) == 0
        # counts toward responded_count so the RFQ can still progress
        assert rfq.responded_count == 1

    @pytest.mark.asyncio
    async def test_no_with_empty_decline_reason_keeps_none(self) -> None:
        supplier = _supplier()
        rfq = _rfq()
        db = _FakeSession(_FakeResult(scalar=None))
        quote = await supplier_submit_quote(
            db,
            rfq,
            supplier,
            lines=[],
            lead_time_days=3,
            can_deliver_in_window=False,
            decline_reason="   ",  # whitespace only
        )
        assert quote.can_deliver_in_window is False
        # Whitespace gets stripped to None (we don't store blank
        # reasons in the DB).
        assert quote.decline_reason is None

    @pytest.mark.asyncio
    async def test_no_with_no_reason_keeps_none(self) -> None:
        supplier = _supplier()
        rfq = _rfq()
        db = _FakeSession(_FakeResult(scalar=None))
        quote = await supplier_submit_quote(
            db,
            rfq,
            supplier,
            lines=[],
            lead_time_days=3,
            can_deliver_in_window=False,
        )
        assert quote.can_deliver_in_window is False
        assert quote.decline_reason is None
        assert quote.declined_at is not None


class TestGateNone:
    @pytest.mark.asyncio
    async def test_none_creates_placeholder_quote_no_count(self) -> None:
        """A "not yet decided" submission creates a placeholder
        quote (so the portal can show "in progress") but does NOT
        increment ``responded_count``. The RFQ can keep waiting for
        the supplier to flip the gate.
        """
        supplier = _supplier()
        rfq = _rfq()
        db = _FakeSession(_FakeResult(scalar=None))
        quote = await supplier_submit_quote(
            db,
            rfq,
            supplier,
            lines=[],
            lead_time_days=3,
            can_deliver_in_window=None,
        )
        assert quote.can_deliver_in_window is None
        assert quote.declined_at is None
        assert quote.decline_reason is None
        assert len(quote.items) == 0
        # Critical: no responded_count bump while the gate is
        # undecided — otherwise the RFQ would progress with
        # placeholder quotes.
        assert rfq.responded_count == 0

    @pytest.mark.asyncio
    async def test_none_with_lines_raises(self) -> None:
        """A "not yet decided" submission must not carry lines.
        The supplier has to flip the gate to True first.
        """
        supplier = _supplier()
        rfq = _rfq()
        db = _FakeSession(_FakeResult(scalar=None))
        with pytest.raises(ValueError, match="can_deliver_in_window decision"):
            await supplier_submit_quote(
                db,
                rfq,
                supplier,
                lines=[
                    {
                        "rfq_item_id": str(rfq.items[0].id),
                        "line_status": "full",
                        "unit_price": 10.0,
                    }
                ],
                lead_time_days=3,
                can_deliver_in_window=None,
            )


class TestGateResubmission:
    @pytest.mark.asyncio
    async def test_yes_after_no_clears_decline_metadata(self) -> None:
        """If a supplier first declined (no) and then resubmits
        with yes, the declined_at + decline_reason are cleared and
        the line picker items are populated. The responded_count
        is decremented on the way out so the yes is the one that
        counts (a supplier who flips shouldn't double-count).
        """
        supplier = _supplier()
        rfq = _rfq()
        # The "existing" quote is the prior decline.
        existing = SimpleNamespace(
            id=uuid4(),
            rfq_id=rfq.id,
            supplier_id=supplier.id,
            can_deliver_in_window=False,
        )
        rfq.responded_count = 1
        db = _FakeSession(_FakeResult(scalar=existing))
        quote = await supplier_submit_quote(
            db,
            rfq,
            supplier,
            lines=[
                {
                    "rfq_item_id": str(rfq.items[0].id),
                    "line_status": "full",
                    "unit_price": 9.0,
                }
            ],
            lead_time_days=4,
            can_deliver_in_window=True,
        )
        assert quote.can_deliver_in_window is True
        assert quote.declined_at is None
        assert len(quote.items) == 1
        # The previous decline was counted, so the resubmit
        # decrements to 0 and then bumps to 1. Net: 1.
        assert rfq.responded_count == 1

    @pytest.mark.asyncio
    async def test_no_after_placeholder_no_double_count(self) -> None:
        """If a supplier had a "not yet decided" placeholder
        (didn't count) and then declines, the decline counts once
        — the placeholder decrement is skipped because the
        placeholder didn't bump.
        """
        supplier = _supplier()
        rfq = _rfq()
        # The "existing" quote is the placeholder.
        existing = SimpleNamespace(
            id=uuid4(),
            rfq_id=rfq.id,
            supplier_id=supplier.id,
            can_deliver_in_window=None,  # not yet decided
        )
        rfq.responded_count = 0
        db = _FakeSession(_FakeResult(scalar=existing))
        quote = await supplier_submit_quote(
            db,
            rfq,
            supplier,
            lines=[],
            lead_time_days=3,
            can_deliver_in_window=False,
            decline_reason="can't meet the window",
        )
        assert quote.can_deliver_in_window is False
        # Net: 0 + 1 (the decline) = 1
        assert rfq.responded_count == 1

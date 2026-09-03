"""
Marketplace Simulator — audit log of supplier bid wars.

A sim run is *bound to an RFQ* (no separate header table). Each row in
``market_sim_events`` is one event in the timeline of a single RFQ's
bid war (``run_start``, ``bid_arrived``, ``round_close``,
``counter_offer``, ``run_end``). The current round and last-used
seed are tracked on ``rfqs.extra`` JSONB so the RFQ stays the
single source of truth.

See ``app/services/market_sim.py`` for the engine that writes these
rows, and ``app/api/v1/rfq.py::simulate_bidding`` for the entry point.
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class MarketSimEventType(str, enum.Enum):
    """Discriminator for a row in ``market_sim_events``."""

    RUN_START = "run_start"          # sim started a new run for this RFQ
    BID_ARRIVED = "bid_arrived"      # one supplier's bid landed
    ROUND_CLOSE = "round_close"      # compare_quotes picked a winner
    COUNTER_OFFER = "counter_offer"  # buyer sent back a counter-offer
    RUN_END = "run_end"              # run completed (round 1 or round 2)


class MarketSimEvent(Base, TimestampMixin):
    """One event in the bid-war timeline of an RFQ.

    The ``ts`` column is wall-clock (set when the row is inserted) and
    is the sort key the frontend uses to drive its 5-second polling
    loop (``WHERE rfq_id = ? AND ts > ?``).
    """

    __tablename__ = "market_sim_events"

    rfq_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rfqs.id", ondelete="CASCADE"),
        nullable=False,
    )
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True,
    )
    round: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1,
        comment="1 for round 1, 2 for the counter-offer round, etc.",
    )
    # Use a String column with a Pydantic-side enum (see MarketSimEventType
    # above). This matches the rfqs/sync conflict patterns where the
    # application validates values; the schema stays portable and trivial.
    event_type: Mapped[str] = mapped_column(
        String(40), nullable=False, index=True,
    )
    supplier_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("suppliers.id", ondelete="SET NULL"),
        nullable=True,
    )
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        # Dominant read: "all events for this RFQ in time order".
        Index("ix_market_sim_events_rfq_id_ts", "rfq_id", "ts"),
        CheckConstraint("round >= 1", name="ck_market_sim_events_round_positive"),
    )


__all__ = ["MarketSimEvent", "MarketSimEventType"]

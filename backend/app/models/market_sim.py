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
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class MarketSimEventType(str, enum.Enum):
    """Discriminator for a row in ``market_sim_events``."""

    RUN_START = "run_start"          # sim started a new run for this RFQ
    BID_ARRIVED = "bid_arrived"      # one supplier's bid landed
    ROUND_CLOSE = "round_close"      # compare_quotes picked a winner
    COUNTER_OFFER = "counter_offer"  # buyer sent back a counter-offer
    RUN_END = "run_end"              # run completed (round 1 or round 2)


class EventVisibility(str, enum.Enum):
    """Who may see a ``market_sim_events`` row's full payload.

    * ``public`` — every authenticated caller can see the full event
      (used for ``run_start``, ``bid_arrived``, ``round_close``,
      ``run_end``, and any future event that isn't classified).
    * ``winner_only`` — only the winning supplier (and admins) can
      see the full payload. Used for ``counter_offer`` events: the
      buyer's counter-offer terms are classified procurement
      information and must not leak to the losing bidders — that
      would let them game round 2 to undercut the target exactly.
    """

    PUBLIC = "public"
    WINNER_ONLY = "winner_only"


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
    # Classification (added 2026-09-03, migration 0004). The
    # default of 'public' covers all rows that existed before the
    # counter-offer was classified — only new counter_offer events
    # use 'winner_only'.
    visibility: Mapped[str] = mapped_column(
        String(20), nullable=False, default=EventVisibility.PUBLIC.value, index=True,
    )
    # Supplier ids that may see the full payload when visibility is
    # 'winner_only'. Populated by the engine with [winner.supplier_id]
    # for counter_offer events. Today no supplier endpoint reads
    # this, but the column is in place so the rule works the moment
    # a supplier portal ships.
    visible_to_supplier_ids: Mapped[list[UUID] | None] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=True,
    )

    __table_args__ = (
        # Dominant read: "all events for this RFQ in time order".
        Index("ix_market_sim_events_rfq_id_ts", "rfq_id", "ts"),
        # Dominant read for the supplier portal (when it ships):
        # "events for this RFQ that this supplier can see".
        # Index("ix_market_sim_events_visibility", "rfq_id", "visibility"),  # temp disabled for seed
        CheckConstraint("round >= 1", name="ck_market_sim_events_round_positive"),
        # Belt-and-braces DB-level check on the visibility value —
        # a bad write from a future code path can't smuggle a typo
        # past the application.
        CheckConstraint(
            "visibility IN ('public', 'winner_only')",
            name="ck_market_sim_events_visibility",
        ),
    )


__all__ = ["MarketSimEvent", "MarketSimEventType", "EventVisibility"]

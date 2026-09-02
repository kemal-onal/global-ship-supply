"""
AIS (Automatic Identification System) position data.

Stores synthetic position reports produced by the ``sim`` package
(see ``/api/v1/internal/ais/ingest``). This table is intentionally
isolated from the rest of the schema:

* **No foreign keys** to ``vessels`` or ``ports`` — synthetic MMSIs
  do not match the real vessel master, and we want to be able to
  ingest reports even when the sim is in error states.
* **A ``source`` column** distinguishes sim data from any future
  real AIS feed ingestion.

If you need to filter out sim data from a query, use
``WHERE source = 'sim'`` (or, if you only ever have sim data,
``WHERE source IS NOT NULL`` for safety).
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    Index,
    Integer,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class AisSource(str, enum.Enum):
    """Origin of an AIS position report row."""

    SIM = "sim"  # produced by the local simulator
    UNKNOWN = "unknown"  # placeholder for future ingestion paths


class AisEventType(str, enum.Enum):
    """Type of event captured in this row."""

    POSITION_REPORT = "position_report"
    ETA_CHANGE = "eta_change"
    PORT_ARRIVAL = "port_arrival"
    PORT_DEPARTURE = "port_departure"
    WEATHER_DELAY = "weather_delay"
    ROUTE_DEVIATION = "route_deviation"


class AisPositionReport(Base, TimestampMixin):
    """A single position report (and related AIS events).

    The same table stores every event type the simulator emits; the
    ``event_type`` column discriminates. The ``payload`` JSONB column
    carries event-type-specific data (``old_eta``/``new_eta`` for
    ``eta_change``, etc.). For ``position_report`` rows, the typed
    columns are populated; for other events, they may be NULL.
    """

    __tablename__ = "ais_position_reports"

    # Common fields (populated for all event types).
    #
    # ``values_callable`` tells SQLAlchemy's native Postgres ``Enum`` to use
    # the *value* of each member (e.g. ``"position_report"``) rather than the
    # Python identifier name (``"POSITION_REPORT"``) when binding parameters
    # and comparing against the DB. Without this, inserts fail with
    # ``invalid input value for enum aiseventtype: "POSITION_REPORT"``.
    event_type: Mapped[AisEventType] = mapped_column(
        Enum(AisEventType, values_callable=lambda e: [m.value for m in e]),
        nullable=False, index=True,
    )
    event_ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True,
        comment="Simulation-time timestamp (the 'as-of' time of the event).",
    )
    source: Mapped[AisSource] = mapped_column(
        Enum(AisSource, values_callable=lambda e: [m.value for m in e]),
        nullable=False, index=True, default=AisSource.SIM,
    )
    mmsi: Mapped[str] = mapped_column(String(9), nullable=False, index=True)
    scenario: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True,
        comment="Scenario name that produced this event (e.g. 'default_med').",
    )
    seed: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
        comment="RNG seed that produced this event (for replay).",
    )

    # Position-report fields (NULL for non-position events).
    imo: Mapped[str | None] = mapped_column(String(7), nullable=True, index=True)
    vessel_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    vessel_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    sog: Mapped[float | None] = mapped_column(Float, nullable=True)
    cog: Mapped[float | None] = mapped_column(Float, nullable=True)
    heading: Mapped[float | None] = mapped_column(Float, nullable=True)
    nav_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    destination_port_id: Mapped[str | None] = mapped_column(
        String(5), nullable=True, index=True,
        comment="UN/LOCODE of next port of call.",
    )
    eta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    draught: Mapped[float | None] = mapped_column(Float, nullable=True)
    flag: Mapped[str | None] = mapped_column(String(2), nullable=True)
    length: Mapped[float | None] = mapped_column(Float, nullable=True)
    beam: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Free-form payload for event-type-specific data.
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        # Common query: "latest positions for vessel X" — needs mmsi + ts.
        Index("ix_ais_position_reports_mmsi_event_ts", "mmsi", "event_ts"),
        # Common query: "all position reports in time range" — for dashboards.
        Index("ix_ais_position_reports_event_ts_event_type", "event_ts", "event_type"),
        # Sanity: lat/lon must be in range when present.
        CheckConstraint(
            "lat IS NULL OR (lat >= -90 AND lat <= 90)",
            name="lat_in_range",
        ),
        CheckConstraint(
            "lon IS NULL OR (lon >= -180 AND lon <= 180)",
            name="lon_in_range",
        ),
        # Sanity: mmsi is 9 digits.
        CheckConstraint(
            "mmsi ~ '^[0-9]{9}$'",
            name="mmsi_9_digits",
        ),
    )


__all__ = ["AisPositionReport", "AisEventType", "AisSource"]

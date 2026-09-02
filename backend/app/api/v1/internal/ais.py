"""Internal AIS ingest endpoints.

Receives batches of position reports and other events from the
``sim`` package (see ``backend/sim/runner.py``) and persists them to
the ``ais_position_reports`` table.

Security model
--------------

These endpoints are **not** protected by JWT. They are intended to be
reachable only on the loopback interface (``127.0.0.1:8000``) or
within a private Docker network. The data they accept is always
synthetic (the simulator uses unassigned MID 9xx MMSIs) and the table
they write to has no foreign keys to any other table — so even if the
endpoint is accidentally exposed, the worst case is junk rows in
``ais_position_reports``, which you can filter with
``WHERE source = 'sim'``.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from app.deps.auth import DBSession
from app.models.ais import AisEventType, AisPositionReport, AisSource

router = APIRouter()


# --- request schemas ---------------------------------------------------

class PositionReportIn(BaseModel):
    """One position report (or other AIS event) from the simulator."""

    event_type: str = Field(default="position_report")
    ts: datetime
    mmsi: str = Field(min_length=9, max_length=9)
    imo: str | None = Field(default=None, min_length=7, max_length=7)
    vessel_name: str | None = None
    vessel_type: str | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    sog: float | None = Field(default=None, ge=0, le=50)
    cog: float | None = Field(default=None, ge=0, lt=360)
    heading: float | None = Field(default=None, ge=0, lt=360)
    nav_status: str | None = None
    destination_port_id: str | None = None
    eta: datetime | None = None
    draught: float | None = None
    flag: str | None = None
    length: float | None = None
    beam: float | None = None
    payload: dict[str, Any] | None = None

    @field_validator("mmsi")
    @classmethod
    def _mmsi_digits(cls, v: str) -> str:
        if not v.isdigit():
            raise ValueError("mmsi must be 9 digits")
        return v


class IngestBatchIn(BaseModel):
    """A batch of reports/events from the simulator."""

    source: str = "sim"
    scenario: str | None = None
    seed: int | None = None
    reports: list[PositionReportIn]


# --- response schemas --------------------------------------------------

class IngestBatchOut(BaseModel):
    accepted: int
    rejected: int
    rejected_reasons: list[str] = []


# --- ingest endpoint ---------------------------------------------------

@router.post("/ingest", response_model=IngestBatchOut)
async def ingest_batch(
    payload: IngestBatchIn,
    db: DBSession,
) -> IngestBatchOut:
    """Ingest a batch of position reports/events.

    Validates the batch and inserts into ``ais_position_reports``.
    Returns counts of accepted and rejected entries. Rejections are
    *per-batch* (one bad row does not block the others) and the
    reasons are returned in the response for the sim to log.
    """
    # Validate source
    try:
        source_enum = AisSource(payload.source)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown source: {payload.source!r}. Expected 'sim' or 'unknown'.",
        )

    accepted = 0
    rejected = 0
    rejected_reasons: list[str] = []

    for report in payload.reports:
        try:
            # ``.value`` is the lowercase Postgres enum literal;
            # ``.name`` would be the Python identifier (uppercase)
            # which Postgres rejects.
            event_type_value = AisEventType(report.event_type).value
        except ValueError:
            rejected += 1
            rejected_reasons.append(
                f"mmsi={report.mmsi}: unknown event_type={report.event_type!r}"
            )
            continue

        row = AisPositionReport(
            event_type=event_type_value,
            event_ts=report.ts,
            source=source_enum.value,
            mmsi=report.mmsi,
            scenario=payload.scenario,
            seed=payload.seed,
            imo=report.imo,
            vessel_name=report.vessel_name,
            vessel_type=report.vessel_type,
            lat=report.lat,
            lon=report.lon,
            sog=report.sog,
            cog=report.cog,
            heading=report.heading,
            nav_status=report.nav_status,
            destination_port_id=report.destination_port_id,
            eta=report.eta,
            draught=report.draught,
            flag=report.flag,
            length=report.length,
            beam=report.beam,
            payload=report.payload,
        )
        db.add(row)
        accepted += 1

    await db.commit()
    return IngestBatchOut(
        accepted=accepted,
        rejected=rejected,
        rejected_reasons=rejected_reasons[:20],  # cap response size
    )


# --- query endpoint (for the dashboard, future tests) ------------------

@router.get("/positions")
async def list_positions(
    db: DBSession,
    mmsi: str | None = Query(default=None, description="Filter by MMSI"),
    event_type: AisEventType | None = Query(default=None),
    scenario: str | None = Query(default=None),
    source: AisSource | None = Query(default=None),
    limit: int = Query(default=100, le=1000),
) -> list[dict[str, Any]]:
    """Query ingested position reports.

    Intended primarily for debugging and integration tests; the main
    consumer dashboards will use streaming endpoints.
    """
    stmt = select(AisPositionReport).order_by(AisPositionReport.event_ts.desc())
    if mmsi:
        stmt = stmt.where(AisPositionReport.mmsi == mmsi)
    if event_type is not None:
        stmt = stmt.where(AisPositionReport.event_type == event_type)
    if scenario is not None:
        stmt = stmt.where(AisPositionReport.scenario == scenario)
    if source is not None:
        stmt = stmt.where(AisPositionReport.source == source)
    stmt = stmt.limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(r.id),
            "event_type": r.event_type.value,
            "event_ts": r.event_ts.isoformat(),
            "source": r.source.value,
            "mmsi": r.mmsi,
            "imo": r.imo,
            "vessel_name": r.vessel_name,
            "lat": r.lat,
            "lon": r.lon,
            "sog": r.sog,
            "cog": r.cog,
            "nav_status": r.nav_status,
            "destination_port_id": r.destination_port_id,
            "eta": r.eta.isoformat() if r.eta else None,
            "scenario": r.scenario,
            "payload": r.payload,
        }
        for r in rows
    ]


@router.get("/health")
async def ingest_health() -> dict[str, Any]:
    """Liveness check for the ingest endpoint. No auth, no DB hit."""
    return {"status": "ok", "endpoint": "internal/ais/ingest"}

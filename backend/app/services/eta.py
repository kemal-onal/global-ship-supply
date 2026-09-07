"""ETA snapshot for the marketplace redesign.

When the company fans out an RFQ, it captures the vessel's most
recent AIS-reported ETA for the order's destination port. This is
a *snapshot*, not a live join — once written to
``Order.eta_at_port`` it stays put until the next fan-out.

The snapshot answers two questions the marketplace UI cares about:

* "When is the vessel expected at the port?" — drives the warning
  in the marketplace lattice if a supplier's lead time would push
  the order past the ETA.
* "Has the vessel reported this port at all in the last 6 hours?"
  — drives a "no recent AIS" warning when ``eta_at_port`` is null.

Why 6h, not 24h or 30 minutes? A vessel transiting at 12 knots
covers ~540 NM in 24h. Six hours is roughly the inter-report
interval the sim produces and the freshness we need to spot
"stale" (no longer en route) reports. Anything older than 6h is
likely a transiting vessel that's already arrived or changed plans
without an update.

Why a "snapshot" and not a live join: live joins are a footgun
in this domain — the AIS data is synthetic, the vessel is
anonymized, and the order's ETA should be a stable property of
the order for the duration of the marketplace flow. The supplier
sees ``order.eta_at_port``; they don't reach into the AIS table
themselves.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.ais import AisPositionReport
from app.models.order import Order
from app.models.vessel import Vessel


# Staleness window for "the vessel is still en route to this port".
# Configurable via env so a future ops change can tighten it
# (e.g. when real AIS replaces the sim).
_ETA_FRESHNESS_HOURS = 6


@dataclass(slots=True)
class EtaSnapshot:
    """Result of an ETA snapshot for a given (vessel, port) pair.

    * ``eta`` — the vessel's most recent AIS-reported ETA for the
      port, or None if no report in the freshness window.
    * ``last_report_ts`` — when the report was emitted (the
      ``event_ts`` column), or None. Drives the "no recent AIS"
      warning independently of ``eta``.
    * ``source_report_id`` — the AIS row's id, for traceability
      (audit log can record "ETA sourced from report X"). None
      when there's no report.
    * ``is_stale`` — True when the report is older than the
      freshness window, even if present. The UI uses this to
      distinguish "no data" from "old data".
    """

    eta: datetime | None
    last_report_ts: datetime | None
    source_report_id: str | None
    is_stale: bool


async def snapshot_eta_for_order(db: AsyncSession, order: Order) -> EtaSnapshot:
    """Take an ETA snapshot for an order, based on the most recent
    AIS position report where ``destination_port_id == order.port.unlocode``.

    Does **not** write to the order — that's the caller's job. The
    function is pure read so it can be used both at fan-out time
    (to populate ``order.eta_at_port``) and at compose time (to
    show the lattice warning if lead times are too long).

    The vessel is looked up via ``order.vessel_id``; the AIS rows
    are keyed by MMSI. If the order's vessel has no MMSI, the
    snapshot is empty (no report can be attributed to it).
    """
    vessel = (await db.execute(
        select(Vessel).where(Vessel.id == order.vessel_id)
    )).scalar_one_or_none()
    if vessel is None or not vessel.mmsi:
        return EtaSnapshot(eta=None, last_report_ts=None, source_report_id=None, is_stale=False)

    # The port's UN/LOCODE is the join key into the AIS table.
    # The order doesn't carry the unlocode directly — go through
    # the Port relationship. The selectinload in the orders route
    # already pre-fetches it, so this stays off the wire for the
    # common path.
    port = order.port
    if port is None or not port.unlocode:
        return EtaSnapshot(eta=None, last_report_ts=None, source_report_id=None, is_stale=False)

    now = datetime.now(timezone.utc)
    fresh_since = now - timedelta(hours=_ETA_FRESHNESS_HOURS)

    # Pick the most recent report. ORDER BY event_ts DESC LIMIT 1
    # is fine here — there's an index on (mmsi, event_ts) (see
    # migration 0002) so the planner can use it.
    row = (await db.execute(
        select(AisPositionReport)
        .where(
            AisPositionReport.mmsi == vessel.mmsi,
            AisPositionReport.destination_port_id == port.unlocode,
            AisPositionReport.event_ts >= fresh_since,
        )
        .order_by(AisPositionReport.event_ts.desc())
        .limit(1)
    )).scalar_one_or_none()

    if row is None:
        # No fresh report. Look for *any* report in the last 30 days
        # so the UI can show "last seen 3d ago" rather than just "—".
        stale = (await db.execute(
            select(AisPositionReport)
            .where(
                AisPositionReport.mmsi == vessel.mmsi,
                AisPositionReport.destination_port_id == port.unlocode,
            )
            .order_by(AisPositionReport.event_ts.desc())
            .limit(1)
        )).scalar_one_or_none()
        if stale is None:
            return EtaSnapshot(eta=None, last_report_ts=None, source_report_id=None, is_stale=False)
        return EtaSnapshot(
            eta=stale.eta,
            last_report_ts=stale.event_ts,
            source_report_id=str(stale.id),
            is_stale=True,
        )

    return EtaSnapshot(
        eta=row.eta,
        last_report_ts=row.event_ts,
        source_report_id=str(row.id),
        is_stale=False,
    )


async def write_eta_to_order(db: AsyncSession, order: Order) -> EtaSnapshot:
    """Snapshot the ETA and persist it to ``order.eta_at_port``.

    Returns the snapshot for the caller's convenience (e.g. for
    including in the API response). The caller is expected to
    ``db.commit()`` afterwards.
    """
    snap = await snapshot_eta_for_order(db, order)
    order.eta_at_port = snap.eta
    return snap


async def snapshot_etd_for_order(db: AsyncSession, order: Order) -> EtaSnapshot:
    """Same shape as ``snapshot_eta_for_order`` but reads the
    vessel's ETD (estimated time of departure) from AIS instead
    of the ETA.

    The supplier uses the ``[eta_at_port, etd_at_port]`` window to
    decide whether they can deliver the package before the vessel
    leaves. ETD can be null in the AIS data (the vessel hasn't
    reported a sailing plan yet) — that becomes a "no recent AIS
    for ETD" warning in the supplier portal, not a block.

    Implementation note: the same ``AisPositionReport`` row carries
    both ``eta`` and ``etd`` columns (see the AIS model). We
    re-derive the row by re-running the freshness-window query
    (the result ordering is identical, so the same report is
    picked). Keeping it as a separate service instead of folding
    both into one ``EtaEtdSnapshot`` keeps the existing ETA call
    sites untouched.
    """
    vessel = (await db.execute(
        select(Vessel).where(Vessel.id == order.vessel_id)
    )).scalar_one_or_none()
    if vessel is None or not vessel.mmsi:
        return EtaSnapshot(eta=None, last_report_ts=None, source_report_id=None, is_stale=False)

    port = order.port
    if port is None or not port.unlocode:
        return EtaSnapshot(eta=None, last_report_ts=None, source_report_id=None, is_stale=False)

    now = datetime.now(timezone.utc)
    fresh_since = now - timedelta(hours=_ETA_FRESHNESS_HOURS)

    row = (await db.execute(
        select(AisPositionReport)
        .where(
            AisPositionReport.mmsi == vessel.mmsi,
            AisPositionReport.destination_port_id == port.unlocode,
            AisPositionReport.event_ts >= fresh_since,
        )
        .order_by(AisPositionReport.event_ts.desc())
        .limit(1)
    )).scalar_one_or_none()

    if row is None:
        stale = (await db.execute(
            select(AisPositionReport)
            .where(
                AisPositionReport.mmsi == vessel.mmsi,
                AisPositionReport.destination_port_id == port.unlocode,
            )
            .order_by(AisPositionReport.event_ts.desc())
            .limit(1)
        )).scalar_one_or_none()
        if stale is None:
            return EtaSnapshot(eta=None, last_report_ts=None, source_report_id=None, is_stale=False)
        return EtaSnapshot(
            eta=stale.etd,
            last_report_ts=stale.event_ts,
            source_report_id=str(stale.id),
            is_stale=True,
        )

    return EtaSnapshot(
        eta=row.etd,
        last_report_ts=row.event_ts,
        source_report_id=str(row.id),
        is_stale=False,
    )


async def write_etd_to_order(db: AsyncSession, order: Order) -> EtaSnapshot:
    """Snapshot the ETD and persist it to ``order.etd_at_port``.

    Mirrors ``write_eta_to_order``. The IMPA-first redesign's
    supplier ETA/ETD gate uses the [eta_at_port, etd_at_port]
    window to decide whether the package can be delivered in time.
    """
    snap = await snapshot_etd_for_order(db, order)
    order.etd_at_port = snap.eta
    return snap

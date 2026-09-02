"""
Event batcher for the AIS simulator.

The ``World`` tick loop yields ``(PositionReport, [SimEvent])`` tuples
for every vessel that changed state in a tick. Before those payloads
are POSTed to the AVS Global backend, they need to be:

* accumulated into a single batch (so we make one HTTP call per
  flush interval, not one per tick),
* converted from dataclass instances to JSON-serializable dicts (the
  ingest endpoint accepts a pydantic ``IngestBatchIn`` model), and
* tagged with the run-level metadata (``source``, ``scenario``,
  ``seed``) the backend uses to label the data.

This module owns that buffering. The HTTP transport itself lives in
``sim.backend_client``.

Design
------

* **No async here.** Building a batch is pure CPU; the I/O happens in
  ``BackendClient.send_batch`` on its own coroutine.
* **Hard size cap.** The ingest endpoint has no server-side batch
  cap, but the simulator caps each flush at
  ``SimSettings.max_batch_size`` (default 50) to keep request
  payloads bounded. The runner flushes *before* adding when the
  batch is full.
* **Two events share one batch.** A position report and a port
  arrival are both legitimate rows in the same ``reports`` list —
  the backend's ``event_type`` column discriminates them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .types import PositionReport, SimEvent


@dataclass
class EventBatch:
    """An in-memory buffer of events ready to be POSTed to the backend.

    The buffer is intentionally dumb: it does not de-duplicate, order
    by timestamp, or coalesce events. The ``World`` tick loop is
    already deterministic and per-tick, so the order in which items
    are added is the order they reach the backend.
    """

    source: str = "sim"
    scenario: str | None = None
    seed: int | None = None
    reports: list[dict[str, Any]] = field(default_factory=list)
    # Optional cap; the runner fills this in from SimSettings so the
    # batch knows when it's full. ``None`` means "no cap".
    max_size: int | None = None

    # --- mutators ----------------------------------------------------

    def add_report(self, report: PositionReport) -> None:
        """Append a position report. Uses the dataclass's own to_dict()."""
        self.reports.append(report.to_dict())

    def add_event(self, event: SimEvent) -> None:
        """Append a non-position event (port_arrival, eta_change, …).

        We do **not** use ``event.to_dict()`` here because that method
        flattens the payload keys to the top level. The backend's
        pydantic ``PositionReportIn`` model ignores unknown top-level
        fields, which would silently drop the event-specific data
        (``port_id``, ``new_eta``, …). Instead we build the dict so
        the payload lands in the dedicated ``payload`` JSONB column.
        """
        row: dict[str, Any] = {
            "event_type": event.event_type,
            "ts": event.ts.isoformat(),
            "mmsi": event.mmsi,
            "payload": dict(event.payload),
        }
        self.reports.append(row)

    def clear(self) -> None:
        """Empty the reports list. Preserves source/scenario/seed/max_size."""
        self.reports.clear()

    # --- queries ------------------------------------------------------

    def is_empty(self) -> bool:
        return len(self.reports) == 0

    def is_full(self) -> bool:
        if self.max_size is None:
            return False
        return len(self.reports) >= self.max_size

    def __len__(self) -> int:
        return len(self.reports)

    # --- serialization -----------------------------------------------

    def to_payload(self) -> dict[str, Any]:
        """Produce the dict the ingest endpoint expects.

        ``scenario`` and ``seed`` are always present in the payload
        (even when None) because the backend's ``IngestBatchIn``
        schema declares them as nullable fields — pydantic will reject
        the request if the keys are missing entirely.
        """
        return {
            "source": self.source,
            "scenario": self.scenario,
            "seed": self.seed,
            "reports": list(self.reports),  # defensive copy
        }


__all__ = ["EventBatch"]

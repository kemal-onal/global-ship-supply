"""Tests for ``sim.events.EventBatch``.

These tests use plain ``PositionReport`` / ``SimEvent`` dataclass
instances — no DB, no HTTP, no FastAPI. The batcher's job is to be
a faithful adapter between the simulator's internal types and the
JSON shape the backend's pydantic ``IngestBatchIn`` expects, so we
compare the produced dicts against the live pydantic schema.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from sim.events import EventBatch
from sim.types import PositionReport, SimEvent, VesselType


def _make_report(**overrides: object) -> PositionReport:
    """Build a minimal valid PositionReport."""
    base: dict[str, object] = dict(
        event_type="position_report",
        ts=datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc),
        mmsi="901000001",
        imo="9900001",
        vessel_name="MV TEST",
        vessel_type=VesselType.CONTAINER_SHIP.value,
        lat=1.26,
        lon=103.82,
        sog=18.5,
        cog=27.5,
        heading=28.0,
        nav_status="under_way_engine",
        destination_port_id="NLRTM",
        eta=datetime(2026, 9, 15, 8, 0, 0, tzinfo=timezone.utc),
        draught=14.5,
        flag="HK",
        length=300.0,
        beam=48.0,
    )
    base.update(overrides)
    return PositionReport(**base)  # type: ignore[arg-type]


def _make_event(event_type: str, **payload: object) -> SimEvent:
    return SimEvent(
        event_type=event_type,
        ts=datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc),
        mmsi="901000001",
        payload=dict(payload),
    )


# --- add_report / add_event -------------------------------------------


class TestAddingItems:
    def test_add_report_stores_dict(self) -> None:
        batch = EventBatch()
        report = _make_report()
        batch.add_report(report)
        assert len(batch) == 1
        assert batch.reports[0]["mmsi"] == "901000001"
        assert batch.reports[0]["event_type"] == "position_report"

    def test_add_event_stores_dict_with_payload(self) -> None:
        batch = EventBatch()
        event = _make_event(
            "port_arrival",
            port_id="NLRTM",
            next_departure_minutes=180,
        )
        batch.add_event(event)
        assert len(batch) == 1
        row = batch.reports[0]
        assert row["event_type"] == "port_arrival"
        assert row["mmsi"] == "901000001"
        # Event-specific data goes under "payload", not at the top
        # level — the backend's pydantic model ignores unknown
        # top-level fields, so flattening would silently drop data.
        assert row["payload"] == {
            "port_id": "NLRTM",
            "next_departure_minutes": 180,
        }

    def test_mixed_reports_and_events_share_one_list(self) -> None:
        batch = EventBatch()
        batch.add_report(_make_report())
        batch.add_event(_make_event("port_departure", port_id="SGSIN"))
        assert len(batch) == 2
        assert batch.reports[0]["event_type"] == "position_report"
        assert batch.reports[1]["event_type"] == "port_departure"
        assert batch.reports[1]["payload"] == {"port_id": "SGSIN"}

    def test_timestamps_are_iso_strings_not_datetimes(self) -> None:
        # The backend expects ISO 8601 strings in the JSON. If a
        # datetime leaks through, json.dumps will fail (no default=
        # handler) and the request will 500.
        batch = EventBatch()
        batch.add_report(_make_report())
        ts = batch.reports[0]["ts"]
        assert isinstance(ts, str)
        # Round-trip cleanly.
        datetime.fromisoformat(ts.replace("Z", "+00:00"))


# --- to_payload ------------------------------------------------------


class TestToPayload:
    def test_payload_shape(self) -> None:
        batch = EventBatch(source="sim", scenario="default_med", seed=42)
        batch.add_report(_make_report())
        payload = batch.to_payload()
        assert set(payload.keys()) == {"source", "scenario", "seed", "reports"}
        assert payload["source"] == "sim"
        assert payload["scenario"] == "default_med"
        assert payload["seed"] == 42
        assert payload["reports"] == batch.reports

    def test_payload_includes_none_scenario_and_seed(self) -> None:
        # IngestBatchIn declares scenario/seed as Optional. The keys
        # must be present (even with value None) so pydantic doesn't
        # reject the request for missing required field.
        batch = EventBatch()
        payload = batch.to_payload()
        assert "scenario" in payload
        assert "seed" in payload
        assert payload["scenario"] is None
        assert payload["seed"] is None

    def test_payload_returns_defensive_copy_of_reports(self) -> None:
        batch = EventBatch()
        batch.add_report(_make_report())
        payload = batch.to_payload()
        payload["reports"].append({"sentinel": True})
        # Mutating the returned payload must not affect the batch.
        assert len(batch) == 1


# --- is_empty / is_full / clear / __len__ --------------------------


class TestSizeAndClear:
    def test_is_empty(self) -> None:
        assert EventBatch().is_empty() is True
        batch = EventBatch()
        batch.add_report(_make_report())
        assert batch.is_empty() is False

    def test_is_full_without_max_size_never_full(self) -> None:
        batch = EventBatch()  # max_size=None
        for _ in range(1000):
            batch.add_report(_make_report())
        assert batch.is_full() is False

    def test_is_full_at_exact_max(self) -> None:
        batch = EventBatch(max_size=3)
        batch.add_report(_make_report())
        batch.add_report(_make_report())
        assert batch.is_full() is False
        batch.add_report(_make_report())
        assert batch.is_full() is True

    def test_clear_empties_reports_keeps_metadata(self) -> None:
        batch = EventBatch(source="sim", scenario="suez", seed=99, max_size=50)
        batch.add_report(_make_report())
        batch.add_event(_make_event("port_arrival", port_id="EGSUZ"))
        assert len(batch) == 2
        batch.clear()
        assert len(batch) == 0
        assert batch.is_empty() is True
        # Metadata must survive.
        assert batch.source == "sim"
        assert batch.scenario == "suez"
        assert batch.seed == 99
        assert batch.max_size == 50

    def test_len_counts_reports_and_events(self) -> None:
        batch = EventBatch()
        batch.add_report(_make_report())
        batch.add_report(_make_report())
        batch.add_event(_make_event("eta_change", destination_port_id="NLRTM"))
        assert len(batch) == 3


# --- contract with the ingest endpoint ------------------------------


class TestContractWithIngestEndpoint:
    """Sanity check: the dicts we produce must satisfy the backend's
    pydantic ``IngestBatchIn`` model. We import that model here (it's
    in the backend package) and use it to validate the payload."""

    @pytest.fixture
    def ingest_model(self):  # type: ignore[no-untyped-def]
        from app.api.v1.internal.ais import IngestBatchIn
        return IngestBatchIn

    def test_position_report_validates(self, ingest_model) -> None:  # type: ignore[no-untyped-def]
        batch = EventBatch(scenario="default_med", seed=42)
        batch.add_report(_make_report())
        # If this doesn't raise, pydantic accepted the payload.
        model = ingest_model.model_validate(batch.to_payload())
        assert model.reports[0].mmsi == "901000001"
        assert model.reports[0].event_type == "position_report"

    def test_event_validates(self, ingest_model) -> None:  # type: ignore[no-untyped-def]
        batch = EventBatch()
        batch.add_event(
            _make_event(
                "port_arrival",
                port_id="NLRTM",
                next_departure_minutes=240,
            )
        )
        model = ingest_model.model_validate(batch.to_payload())
        assert model.reports[0].event_type == "port_arrival"
        # The payload dict lands in .payload.
        assert model.reports[0].payload == {
            "port_id": "NLRTM",
            "next_departure_minutes": 240,
        }

"""Unit tests for sim.types — dataclass validation rules."""
from __future__ import annotations

import pytest

from sim.types import NavStatus, Port, Vessel, VesselType


# --- Port ---------------------------------------------------------------

class TestPort:
    def test_valid(self) -> None:
        p = Port("SGSIN", "Singapore", "SG", "Singapore", "asia", 1.2644, 103.8200)
        assert p.un_locode == "SGSIN"

    def test_lowercase_locode_normalized(self) -> None:
        # We don't auto-normalize — the input is what it is.
        p = Port("sgsin", "Singapore", "SG", "Singapore", "asia", 1.2644, 103.8200)
        assert p.un_locode == "sgsin"

    def test_bad_locode_length(self) -> None:
        with pytest.raises(ValueError):
            Port("SINGAPORE", "Singapore", "SG", "Singapore", "asia", 1.2644, 103.8200)
        with pytest.raises(ValueError):
            Port("SG", "Singapore", "SG", "Singapore", "asia", 1.2644, 103.8200)

    def test_bad_lat(self) -> None:
        with pytest.raises(ValueError):
            Port("SGSIN", "Singapore", "SG", "Singapore", "asia", 91.0, 103.0)
        with pytest.raises(ValueError):
            Port("SGSIN", "Singapore", "SG", "Singapore", "asia", -91.0, 103.0)

    def test_bad_lon(self) -> None:
        with pytest.raises(ValueError):
            Port("SGSIN", "Singapore", "SG", "Singapore", "asia", 1.0, 181.0)
        with pytest.raises(ValueError):
            Port("SGSIN", "Singapore", "SG", "Singapore", "asia", 1.0, -181.0)


# --- Vessel -------------------------------------------------------------

class TestVessel:
    def test_valid(self) -> None:
        v = Vessel(
            mmsi="901000001", imo="9900001", name="MV TEST",
            vessel_type=VesselType.CONTAINER_SHIP, flag_iso2="HK",
            length_m=300.0, beam_m=48.0, draught_m=14.5, max_speed_knots=22.0,
        )
        assert v.mmsi == "901000001"
        assert v.vessel_type == VesselType.CONTAINER_SHIP

    def test_bad_mmsi_length(self) -> None:
        with pytest.raises(ValueError):
            Vessel(
                mmsi="12345", imo="9900001", name="MV TEST",
                vessel_type=VesselType.CONTAINER_SHIP, flag_iso2="HK",
                length_m=300.0, beam_m=48.0, draught_m=14.5, max_speed_knots=22.0,
            )

    def test_mmsi_must_be_digits(self) -> None:
        with pytest.raises(ValueError):
            Vessel(
                mmsi="90100000A", imo="9900001", name="MV TEST",
                vessel_type=VesselType.CONTAINER_SHIP, flag_iso2="HK",
                length_m=300.0, beam_m=48.0, draught_m=14.5, max_speed_knots=22.0,
            )

    def test_bad_imo(self) -> None:
        with pytest.raises(ValueError):
            Vessel(
                mmsi="901000001", imo="123", name="MV TEST",
                vessel_type=VesselType.CONTAINER_SHIP, flag_iso2="HK",
                length_m=300.0, beam_m=48.0, draught_m=14.5, max_speed_knots=22.0,
            )

    def test_unrealistic_speed(self) -> None:
        with pytest.raises(ValueError):
            Vessel(
                mmsi="901000001", imo="9900001", name="MV TEST",
                vessel_type=VesselType.CONTAINER_SHIP, flag_iso2="HK",
                length_m=300.0, beam_m=48.0, draught_m=14.5, max_speed_knots=60.0,
            )
        with pytest.raises(ValueError):
            Vessel(
                mmsi="901000001", imo="9900001", name="MV TEST",
                vessel_type=VesselType.CONTAINER_SHIP, flag_iso2="HK",
                length_m=300.0, beam_m=48.0, draught_m=14.5, max_speed_knots=0.0,
            )


# --- NavStatus / VesselType are str enums (so JSON serialization works) --

def test_navstatus_is_str() -> None:
    assert NavStatus.UNDER_WAY_ENGINE == "under_way_engine"
    assert NavStatus.UNDER_WAY_ENGINE.value == "under_way_engine"


def test_vessel_type_is_str() -> None:
    assert VesselType.CONTAINER_SHIP == "container_ship"

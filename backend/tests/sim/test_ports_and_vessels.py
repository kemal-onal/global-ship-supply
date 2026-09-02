"""Tests for sim.ports and sim.vessels catalog data."""
from __future__ import annotations

import pytest

from sim.ports import PORTS, get_port, ports_by_region
from sim.vessels import VESSELS, get_vessel


class TestPortsCatalog:
    def test_at_least_50_ports(self) -> None:
        # We hand-picked ~50, so this should always pass.
        assert len(PORTS) >= 50, f"got {len(PORTS)} ports"

    def test_unique_locodes(self) -> None:
        locodes = [p.un_locode for p in PORTS]
        assert len(locodes) == len(set(locodes)), "duplicate UN/LOCODE in catalog"

    def test_major_hubs_present(self) -> None:
        for code in ("SGSIN", "NLRTM", "CNSHA", "USLAX", "EGSUZ", "PAPCN", "HKHKG"):
            assert get_port(code).un_locode == code

    def test_get_unknown_raises(self) -> None:
        with pytest.raises(KeyError):
            get_port("ZZZZZ")

    def test_get_case_insensitive(self) -> None:
        p = get_port("sgsin")
        assert p.un_locode == "SGSIN"

    def test_regions_represented(self) -> None:
        regions = {p.region for p in PORTS}
        # All 5 inhabited continents.
        for r in ("asia", "europe", "africa", "north_america", "south_america", "oceania"):
            assert r in regions, f"region {r!r} missing"

    def test_filter_by_region(self) -> None:
        asia = ports_by_region("asia")
        assert len(asia) >= 10
        assert all(p.region == "asia" for p in asia)


class TestVesselsCatalog:
    def test_at_least_15_vessels(self) -> None:
        assert len(VESSELS) >= 15

    def test_unique_mmsis(self) -> None:
        mmsis = [v.mmsi for v in VESSELS]
        assert len(mmsis) == len(set(mmsis)), "duplicate MMSI in catalog"

    def test_unique_imos(self) -> None:
        imos = [v.imo for v in VESSELS]
        assert len(imos) == len(set(imos)), "duplicate IMO in catalog"

    def test_all_mmsis_synthetic(self) -> None:
        # MID 900-999 is unassigned by ITU — every MMSI must start with 9.
        for v in VESSELS:
            assert v.mmsi.startswith("9"), f"non-synthetic MMSI: {v.mmsi}"

    def test_diverse_types(self) -> None:
        types = {v.vessel_type for v in VESSELS}
        # Should cover at least 4 of the major merchant types.
        assert len(types) >= 4

    def test_get_unknown_raises(self) -> None:
        with pytest.raises(KeyError):
            get_vessel("000000000")

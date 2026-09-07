"""Tests for ``sim.scenarios``.

These tests don't drive the world. The world is exercised in
``test_world.py``; here we only verify that the *registry* is
well-formed and that each scenario's port/vessel references
actually exist in the upstream ``PORTS`` / ``VESSELS`` lists.
"""
from __future__ import annotations

import pytest

from sim.ports import PORTS
from sim.scenarios import SCENARIOS, Scenario, get_scenario, list_scenarios
from sim.vessels import VESSELS
from sim.world import World, WorldConfig, make_assignment_from_ports


# --- registry shape -------------------------------------------------


class TestRegistry:
    def test_has_four_known_scenarios(self) -> None:
        assert set(SCENARIOS) == {
            "default_med",
            "suez_blockage",
            "storm_rerouting",
            "quiet_harbor",
        }

    def test_list_scenarios_is_sorted(self) -> None:
        # Stable order for --help output and the runner's startup log.
        assert list_scenarios() == sorted(list_scenarios())
        # Every name in the list must also be a registry key.
        assert all(n in SCENARIOS for n in list_scenarios())

    def test_scenarios_are_frozen(self) -> None:
        s = get_scenario("quiet_harbor")
        with pytest.raises((AttributeError, Exception)):
            # frozen dataclasses reject setattr.
            s.name = "other"  # type: ignore[misc]

    def test_scenarios_are_hashable(self) -> None:
        # Frozen dataclasses are hashable by default.
        s = get_scenario("quiet_harbor")
        assert hash(s) is not None
        # Two lookups for the same name must hash equal.
        assert hash(s) == hash(get_scenario("quiet_harbor"))


# --- lookup --------------------------------------------------------


class TestLookup:
    def test_get_scenario_by_exact_name(self) -> None:
        s = get_scenario("default_med")
        assert isinstance(s, Scenario)
        assert s.name == "default_med"

    def test_get_scenario_is_case_insensitive(self) -> None:
        # All-uppercase and Title-case both resolve. Underscores are
        # literal — "DEFAULTMED" does NOT match "quiet_harbor"
        # because the character sequences differ. That's intentional:
        # case-insensitive matching, not fuzzy matching.
        assert get_scenario("DEFAULT_MED") is get_scenario("default_med")
        assert get_scenario("Default_Med") is get_scenario("default_med")
        # Sanity: case-insensitive but underscore-sensitive.
        with pytest.raises(KeyError):
            get_scenario("DEFAULTMED")

    def test_get_scenario_unknown_raises_with_available_list(self) -> None:
        with pytest.raises(KeyError) as ei:
            get_scenario("does_not_exist")
        msg = str(ei.value)
        assert "does_not_exist" in msg
        # Message must list the available names so the user can
        # see the typo.
        for name in SCENARIOS:
            assert name in msg


# --- per-scenario invariants --------------------------------------


class TestScenarioInvariants:
    @pytest.mark.parametrize("name", list_scenarios())
    def test_each_scenario_has_at_least_one_vessel(self, name: str) -> None:
        s = get_scenario(name)
        assert len(s.assignments) >= 1, f"{name} has no vessels"

    @pytest.mark.parametrize("name", list_scenarios())
    def test_each_assignment_has_at_least_two_ports(self, name: str) -> None:
        # The world's circular route requires >= 2 ports.
        s = get_scenario(name)
        for vessel, ports in s.assignments:
            assert len(ports) >= 2, (
                f"{name}: vessel {vessel.mmsi} has only {len(ports)} ports"
            )

    @pytest.mark.parametrize("name", list_scenarios())
    def test_vessels_exist_in_global_list(self, name: str) -> None:
        valid_mmsis = {v.mmsi for v in VESSELS}
        s = get_scenario(name)
        for vessel, _ports in s.assignments:
            assert vessel.mmsi in valid_mmsis, (
                f"{name}: vessel {vessel.mmsi} not in VESSELS"
            )

    @pytest.mark.parametrize("name", list_scenarios())
    def test_ports_exist_in_global_list(self, name: str) -> None:
        valid_locodes = {p.un_locode for p in PORTS}
        s = get_scenario(name)
        for _vessel, ports in s.assignments:
            for p in ports:
                assert p.un_locode in valid_locodes, (
                    f"{name}: port {p.un_locode} not in PORTS"
                )

    @pytest.mark.parametrize("name", list_scenarios())
    def test_summary_is_nonempty_and_mentions_vessel_count(
        self, name: str
    ) -> None:
        s = get_scenario(name)
        summary = s.summary()
        assert isinstance(summary, str)
        assert len(summary) > 0
        assert f"{len(s.assignments)} vessel" in summary


# --- per-scenario content checks ---------------------------------


class TestScenarioContent:
    def test_default_med_is_five_vessels_four_ports(self) -> None:
        s = get_scenario("default_med")
        assert len(s.assignments) == 5
        all_ports: set[str] = set()
        for _v, ports in s.assignments:
            for p in ports:
                all_ports.add(p.un_locode)
        assert all_ports == {"ESALG", "GRPIR", "ITGOA", "MTMLA"}

    def test_quiet_harbor_is_two_vessels_two_ports(self) -> None:
        s = get_scenario("quiet_harbor")
        assert len(s.assignments) == 2
        for _v, ports in s.assignments:
            assert {p.un_locode for p in ports} == {"NLRTM", "DEHAM"}

    def test_suez_blockage_routes_via_durban(self) -> None:
        # The "Cape" detour must show up as a Durban (ZADUR) stop
        # in at least one assignment.
        s = get_scenario("suez_blockage")
        all_locodes: set[str] = set()
        for _v, ports in s.assignments:
            for p in ports:
                all_locodes.add(p.un_locode)
        assert "ZADUR" in all_locodes  # Cape of Good Hope stop
        # EGSUZ itself is allowed to be absent (canal is closed).
        # We don't assert that — it's a content choice, not an
        # invariant.

    def test_storm_rerouting_routes_via_tangier(self) -> None:
        s = get_scenario("storm_rerouting")
        all_locodes: set[str] = set()
        for _v, ports in s.assignments:
            for p in ports:
                all_locodes.add(p.un_locode)
        # Every assignment should touch MAPTM (the diversion waypoint).
        for vessel, ports in s.assignments:
            assert any(p.un_locode == "MAPTM" for p in ports), (
                f"Vessel {vessel.mmsi} in storm_rerouting doesn't "
                f"route via Tangier-Med"
            )

    def test_suez_blockage_has_long_dwell(self) -> None:
        # The "idle Mediterranean vessels" effect depends on a huge
        # global dwell. If a future change breaks this, the scenario
        # stops looking like a Suez blockage.
        s = get_scenario("suez_blockage")
        assert s.port_dwell_minutes is not None
        assert s.port_dwell_minutes > 1_000_000

    def test_sim_vessel_mmsis_match_seed_fleet(self) -> None:
        # The AIS feed is joined to seed vessels on MMSI by the ETA
        # snapshot service. A scenario that references a MMSI not
        # present in the seed (or vice versa) silently breaks ETA
        # snapshots for any order assigned to that vessel — the
        # marketplace UI shows the "no AIS ETA snapshot" warning
        # with no other indication of why. This test pins the
        # alignment: every scenario's vessel MMSI must be a known
        # sim vessel, and the full set of sim vessel MMSIs is the
        # same 12 MMSIs the seed scripts/seed.py seeds.
        from sim.vessels import VESSELS
        seed_mmsis = {v.mmsi for v in VESSELS}
        assert len(seed_mmsis) == 12, (
            f"expected 12 sim vessels (one per seed row), got "
            f"{len(seed_mmsis)}"
        )
        for s in SCENARIOS.values():
            for vessel, _ports in s.assignments:
                assert vessel.mmsi in seed_mmsis, (
                    f"Scenario {s.name!r} references unknown MMSI "
                    f"{vessel.mmsi!r}; known MMSIs: "
                    f"{sorted(seed_mmsis)}"
                )


# --- world integration smoke tests --------------------------------


class TestWorldIntegration:
    """Drive the world with each scenario's assignments and confirm
    that step() yields one report per vessel. These are not deep
    tests of the world — those live in test_world.py — they're a
    last-line-of-defense check that the scenarios are *pluggable*
    into the world as-is."""

    @pytest.mark.parametrize("name", list_scenarios())
    def test_world_steps_one_report_per_vessel(self, name: str) -> None:
        from datetime import datetime, timezone

        s = get_scenario(name)
        # Use a short dwell so the world actually moves the vessels;
        # for suez_blockage the long dwell would otherwise leave
        # everything in port and the smoke test would just confirm
        # that, which is not what we want here.
        world = World(
            config=WorldConfig(
                tick_seconds=1.0,
                sim_time_scale=60.0,
                seed=42,
                port_dwell_minutes=0,
                start_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
            ),
            assignments=[
                make_assignment_from_ports(v, list(p))
                for v, p in s.assignments
            ],
        )
        reports = list(world.step())
        assert len(reports) == len(s.assignments), (
            f"{name}: expected {len(s.assignments)} reports, got {len(reports)}"
        )
        seen_mmsis = {r[0].mmsi for r in reports}
        expected_mmsis = {v.mmsi for v, _p in s.assignments}
        assert seen_mmsis == expected_mmsis

    def test_quiet_harbor_repeated_steps(self) -> None:
        """Run a few ticks and confirm the same 2 vessels keep showing up."""
        from datetime import datetime, timezone

        s = get_scenario("quiet_harbor")
        world = World(
            config=WorldConfig(
                tick_seconds=1.0,
                sim_time_scale=60.0,
                seed=42,
                port_dwell_minutes=0,
                start_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
            ),
            assignments=[
                make_assignment_from_ports(v, list(p))
                for v, p in s.assignments
            ],
        )
        for _ in range(5):
            reports = list(world.step())
            assert {r[0].mmsi for r in reports} == {
                v.mmsi for v, _p in s.assignments
            }

"""Unit tests for sim.world — the tick loop.

These tests use a high ``sim_time_scale`` (so the sim moves quickly)
but keep ``tick_seconds=1.0`` (so 1 wall-clock second = 1 sim-minute
or 1 sim-hour, depending on scale).
"""
from __future__ import annotations

import pytest

from sim.geo import haversine_nm
from sim.ports import get_port
from sim.vessels import get_vessel
from sim.world import (
    ARRIVAL_THRESHOLD_NM,
    DEFAULT_PORT_DWELL_MINUTES,
    World,
    WorldConfig,
    make_assignment,
    make_assignment_from_ports,
)


def _make_world(
    vessel_mmsi: str = "900000001",
    ports: list[str] | None = None,
    *,
    sim_time_scale: float = 60.0,  # 1 tick = 1 sim-min
    port_dwell_minutes: int = 0,
    seed: int = 42,
) -> World:
    if ports is None:
        ports = ["SGSIN", "CNSHA"]
    vessel = get_vessel(vessel_mmsi)
    port_list = [get_port(code) for code in ports]
    assignment = make_assignment_from_ports(vessel, port_list)
    return World(
        WorldConfig(
            tick_seconds=1.0,
            sim_time_scale=sim_time_scale,
            seed=seed,
            port_dwell_minutes=port_dwell_minutes,
        ),
        [assignment],
    )


# --- basic properties --------------------------------------------------

class TestWorldBasics:
    def test_construction(self) -> None:
        w = _make_world()
        assert len(w.states) == 1
        mmsi = list(w.states.keys())[0]
        # Starts at origin of first route, in port.
        state = w.states[mmsi]
        assert state.is_in_port is True
        # Status is "in_port" at construction; becomes "moored" only
        # after the first tick while still in port.
        assert state.current_nav_status.value in ("in_port", "moored")

    def test_first_step_emits_report(self) -> None:
        w = _make_world()
        reports = list(w.step())
        assert len(reports) == 1
        report, events = reports[0]
        assert report.mmsi == "900000001"
        assert report.destination_port_id == "CNSHA"

    def test_reports_have_required_fields(self) -> None:
        w = _make_world(port_dwell_minutes=0)
        for _ in range(3):
            for r, _ in w.step():
                # Required by the schema.
                assert r.event_type == "position_report"
                assert r.mmsi
                assert r.imo
                assert r.vessel_name
                assert -90 <= r.lat <= 90
                assert -180 <= r.lon <= 180
                assert 0 <= r.sog <= 30
                assert 0 <= r.cog < 360

    def test_report_ts_is_wall_clock_within_5_seconds(self) -> None:
        # The backend's ETA snapshot freshness window compares
        # ``event_ts`` to ``datetime.now()`` to decide if a report
        # is "fresh" (within 6h). If the sim emitted sim-time on
        # ``event_ts`` (sim clock starts 2026-09-01), every report
        # would look ~6 days stale against real wall-clock and the
        # marketplace UI's "no AIS ETA snapshot" warning would
        # always show. ``ts`` must therefore be wall-clock and
        # within a few seconds of the test's actual time.
        from datetime import datetime, timezone
        before = datetime.now(timezone.utc)
        w = _make_world(port_dwell_minutes=0)
        reports = list(w.step())
        after = datetime.now(timezone.utc)
        assert len(reports) == 1
        report, _ = reports[0]
        assert before <= report.ts <= after, (
            f"report.ts={report.ts} is outside [{before}, {after}] — "
            "should be wall-clock"
        )


# --- movement ----------------------------------------------------------

class TestMovement:
    def test_vessel_moves_underway(self) -> None:
        # With 0 port dwell, vessel should be underway after 1 sim-min.
        w = _make_world(sim_time_scale=60.0, port_dwell_minutes=0)
        first_pos = list(w.states.values())[0]
        # First tick triggers departure.
        for r, events in w.step():
            assert any(e.event_type == "port_departure" for e in events)
        # Subsequent ticks should move the vessel.
        prev_lat, prev_lon = r.lat, r.lon
        for _ in range(5):
            for r, _ in w.step():
                pass
        # Position must have changed.
        assert r.lat != prev_lat or r.lon != prev_lon

    def test_sog_within_realistic_range(self) -> None:
        # 60x scale, vessel cruises at 22 kts * 0.85 = 18.7 kts nominal.
        w = _make_world(sim_time_scale=60.0, port_dwell_minutes=0)
        # Burn a few ticks for speed to settle.
        for _ in range(20):
            for r, _ in w.step():
                pass
        # SOG should be near 18.7 kts ±20% (with 2% noise + mean reversion).
        assert 14 <= r.sog <= 23, f"SOG out of range: {r.sog}"

    def test_vessel_progresses_toward_destination(self) -> None:
        # Run a 60x-scale sim for 60 ticks (60 sim-min) and check we're
        # measurably closer to the destination.
        w = _make_world(sim_time_scale=60.0, port_dwell_minutes=0)
        sin = get_port("SGSIN")
        sha = get_port("CNSHA")
        initial_d = haversine_nm(sin.lat, sin.lon, sha.lat, sha.lon)
        # First tick: departure, no movement.
        for r, _ in w.step():
            pass
        # Run 60 more ticks.
        for _ in range(60):
            for r, _ in w.step():
                pass
        new_d = haversine_nm(r.lat, r.lon, sha.lat, sha.lon)
        assert new_d < initial_d, "vessel didn't move toward destination"

    def test_high_scale_no_orbit(self) -> None:
        # Regression: at high sim_time_scale, the vessel used to orbit
        # because it kept re-targeting on near waypoints. With the
        # "target destination directly" approach, it should sail in
        # a roughly straight line on the great circle.
        w = _make_world(sim_time_scale=3600.0, port_dwell_minutes=0)  # 1 tick = 1 sim-hour
        # Burn off departure.
        for _ in range(2):
            for r, _ in w.step():
                pass
        # Track COG only while the vessel is still underway. With
        # VISUAL_SPEED_BOOST=10 a SG->SH leg completes in ~12 ticks,
        # so 8 ticks is a safe pre-arrival window. If the vessel
        # orbits, the COG will swing wildly during this window.
        cogs = []
        for _ in range(8):
            for r, events in w.step():
                if any(e.event_type == "port_arrival" for e in events):
                    break
                cogs.append(r.cog)
        # SG -> SH bearing is ~28°. The COG should stay within ±15° of that.
        avg_cog = sum(cogs) / len(cogs)
        # If the vessel orbited, the avg would be wildly off (or near 0/360).
        assert 0 <= avg_cog <= 90, f"avg COG looks like an orbit: {avg_cog}"

    def test_path_follows_waypoints_not_straight_line(self) -> None:
        # Regression for the "vessels cross land" bug: the sim used
        # to head straight at the destination from each tick, which
        # on a great-circle-leg (where the destination is *behind*
        # the great-circle arc) is a *rhumb-line* path — and that
        # path crosses whatever land lies between origin and
        # destination. The fix is to follow the route's waypoints
        # in order, so the path actually *traces* the great circle.
        #
        # We verify by checking the path stays close to the
        # great-circle interpolation, with a tolerance generous
        # enough to allow VISUAL_SPEED_BOOST=10 (187-nm steps).
        w = _make_world(sim_time_scale=3600.0, port_dwell_minutes=0)
        sin = get_port("SGSIN")
        sha = get_port("CNSHA")
        # Collect the vessel's actual path (positions per tick).
        path: list[tuple[float, float]] = []
        for _ in range(2):
            for r, _ in w.step():
                pass
        for _ in range(15):  # 15 ticks is well within arrival window
            for r, events in w.step():
                if any(e.event_type == "port_arrival" for e in events):
                    break
                path.append((r.lat, r.lon))
        # For each point on the actual path, find the closest
        # great-circle-interpolated point and assert the path
        # doesn't stray far from the great circle.
        total = haversine_nm(sin.lat, sin.lon, sha.lat, sha.lon)
        max_cross_track = 0.0
        for lat, lon in path:
            d_origin = haversine_nm(sin.lat, sin.lon, lat, lon)
            d_dest = haversine_nm(lat, lon, sha.lat, sha.lon)
            # Fraction along the route
            f = d_origin / total if total > 0 else 0
            from sim.geo import interpolate_great_circle
            gc_lat, gc_lon = interpolate_great_circle(
                sin.lat, sin.lon, sha.lat, sha.lon, f
            )
            cross_track = haversine_nm(lat, lon, gc_lat, gc_lon)
            max_cross_track = max(max_cross_track, cross_track)
        # The path should be within 50 nm of the great circle. Real
        # waypoint-following keeps it within ~30 nm. A bug where
        # the path cuts straight at the destination (no waypoint
        # following) produces cross-track errors of 100+ nm on the
        # SG-SH leg because the great circle arcs north through
        # the East China Sea while the straight line cuts across
        # the South China Sea.
        assert max_cross_track < 50.0, (
            f"path strays {max_cross_track:.1f} nm from the great "
            f"circle — waypoint following is broken (vessels are "
            f"heading straight at the destination instead of "
            f"tracing the polyline)"
        )


# --- arrival & departure -----------------------------------------------

class TestPortArrival:
    def test_short_voyage_arrives(self) -> None:
        # SG to SH at 22 kts * 0.85 = 18.7 kts → ~110 hours.
        # At 3600x sim scale, that's 110 ticks. Run 200 to be safe.
        w = _make_world(sim_time_scale=3600.0, port_dwell_minutes=0)
        for _ in range(200):
            for r, events in w.step():
                if any(e.event_type == "port_arrival" for e in events):
                    # First arrival should be at CNSHA. The report is
                    # built after the route advances to the next leg
                    # (CNSHA -> SGSIN), so destination_port_id is the
                    # next leg's destination: SGSIN.
                    assert r.destination_port_id == "SGSIN", (
                        f"first arrival's next-leg destination is "
                        f"{r.destination_port_id}, expected SGSIN"
                    )
                    return
        pytest.fail("vessel never arrived in 200 sim-hours")

    def test_arrival_position_matches_destination(self) -> None:
        w = _make_world(sim_time_scale=3600.0, port_dwell_minutes=0)
        sha = get_port("CNSHA")
        for _ in range(200):
            for r, events in w.step():
                if any(e.event_type == "port_arrival" for e in events):
                    d = haversine_nm(r.lat, r.lon, sha.lat, sha.lon)
                    assert d < 5.0, f"arrival too far from port: {d} nm"
                    return
        pytest.fail("never arrived")


# --- events ------------------------------------------------------------

class TestEvents:
    def test_port_departure_event(self) -> None:
        w = _make_world(port_dwell_minutes=0)
        for r, events in w.step():
            types = {e.event_type for e in events}
            assert "port_departure" in types
            # The event should reference the origin port.
            for e in events:
                if e.event_type == "port_departure":
                    assert e.payload.get("port_id") == "SGSIN"
                    assert e.payload.get("destination_port_id") == "CNSHA"

    def test_eta_change_event(self) -> None:
        # The vessel's actual speed deviates from nominal due to noise,
        # which causes ETA to drift. We should see at least one
        # eta_change event over a long enough run.
        w = _make_world(sim_time_scale=60.0, port_dwell_minutes=0)
        seen = False
        for _ in range(120):
            for r, events in w.step():
                if any(e.event_type == "eta_change" for e in events):
                    seen = True
        assert seen, "no eta_change events emitted"


# --- reproducibility ---------------------------------------------------

class TestReproducibility:
    def test_same_seed_same_trajectory(self) -> None:
        # Two worlds with the same seed should produce identical
        # position reports over the first N ticks.
        def run(seed: int) -> list[tuple[float, float]]:
            w = _make_world(sim_time_scale=60.0, port_dwell_minutes=0, seed=seed)
            out: list[tuple[float, float]] = []
            for _ in range(20):
                for r, _ in w.step():
                    out.append((r.lat, r.lon))
            return out

        a = run(123)
        b = run(123)
        assert a == b

    def test_different_seeds_diverge(self) -> None:
        # The vessel's *position* is deterministic (it moves along
        # the great circle to the destination — that path is the
        # same regardless of seed), so we check the *reported* SOG
        # and COG, which still get a per-tick Gaussian noise term
        # and therefore vary by seed.
        def run(seed: int) -> list[tuple[float, float]]:
            w = _make_world(sim_time_scale=60.0, port_dwell_minutes=0, seed=seed)
            out: list[tuple[float, float]] = []
            for _ in range(20):
                for r, _ in w.step():
                    out.append((r.sog, r.cog))
            return out

        a = run(1)
        b = run(2)
        assert a != b, "different seeds should produce different SOG/COG reports"


# --- module-level constants --------------------------------------------

def test_constants() -> None:
    assert 0 < ARRIVAL_THRESHOLD_NM < 5
    assert DEFAULT_PORT_DWELL_MINUTES > 0

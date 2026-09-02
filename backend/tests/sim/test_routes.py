"""Unit tests for sim.routes — great-circle route generation."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from sim.geo import haversine_nm
from sim.ports import get_port
from sim.routes import (
    DEFAULT_SERVICE_SPEED_KNOTS,
    DEFAULT_STEP_NM,
    build_circular_route,
    build_route,
)


# --- build_route --------------------------------------------------------

class TestBuildRoute:
    def test_basic(self) -> None:
        sin = get_port("SGSIN")
        rtm = get_port("NLRTM")
        route = build_route(sin, rtm)
        assert route.origin == sin
        assert route.destination == rtm
        assert route.total_distance_nm > 0
        assert route.planned_duration_hours > 0
        # Waypoints should be at the configured step interval.
        assert len(route.waypoints) > 0

    def test_total_distance_matches_great_circle(self) -> None:
        sin = get_port("SGSIN")
        sha = get_port("CNSHA")
        route = build_route(sin, sha, service_speed_knots=18.0, step_nm=100.0)
        gc = haversine_nm(sin.lat, sin.lon, sha.lat, sha.lon)
        # Total stored distance should match the great-circle distance.
        assert abs(route.total_distance_nm - gc) < 0.1

    def test_waypoint_step_size(self) -> None:
        sin = get_port("SGSIN")
        sha = get_port("CNSHA")
        step = 100.0
        route = build_route(sin, sha, step_nm=step, service_speed_knots=18.0)
        # First waypoint should be ~step nm from origin.
        d0 = haversine_nm(sin.lat, sin.lon, route.waypoints[0].lat, route.waypoints[0].lon)
        assert abs(d0 - step) < 1.0, f"first waypoint at {d0} nm, expected ~{step}"

    def test_waypoints_converge_at_destination(self) -> None:
        sin = get_port("SGSIN")
        sha = get_port("CNSHA")
        route = build_route(sin, sha, step_nm=50.0, service_speed_knots=18.0)
        last = route.waypoints[-1]
        assert abs(last.lat - sha.lat) < 1e-6
        assert abs(last.lon - sha.lon) < 1e-6

    def test_with_depart_at(self) -> None:
        sin = get_port("SGSIN")
        sha = get_port("CNSHA")
        depart = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
        route = build_route(sin, sha, service_speed_knots=18.0, step_nm=100.0, depart_at=depart)
        # All waypoints should have ETAs.
        for wp in route.waypoints:
            assert wp.eta is not None
        # First ETA should be after depart, last should be at the end.
        assert route.waypoints[0].eta > depart  # type: ignore[operator]
        last_eta = route.waypoints[-1].eta
        expected_total = timedelta(hours=route.planned_duration_hours)
        assert abs((last_eta - depart) - expected_total) < timedelta(seconds=1)  # type: ignore

    def test_same_origin_destination_raises(self) -> None:
        sin = get_port("SGSIN")
        with pytest.raises(ValueError):
            build_route(sin, sin)

    def test_invalid_speed_raises(self) -> None:
        sin = get_port("SGSIN")
        sha = get_port("CNSHA")
        with pytest.raises(ValueError):
            build_route(sin, sha, service_speed_knots=0)
        with pytest.raises(ValueError):
            build_route(sin, sha, service_speed_knots=-1)

    def test_invalid_step_raises(self) -> None:
        sin = get_port("SGSIN")
        sha = get_port("CNSHA")
        with pytest.raises(ValueError):
            build_route(sin, sha, step_nm=0)


# --- build_circular_route ----------------------------------------------

class TestCircularRoute:
    def test_three_ports(self) -> None:
        sin = get_port("SGSIN")
        rtm = get_port("NLRTM")
        sha = get_port("CNSHA")
        routes = build_circular_route([sin, rtm, sha])
        assert len(routes) == 3
        assert routes[0].origin == sin and routes[0].destination == rtm
        assert routes[1].origin == rtm and routes[1].destination == sha
        assert routes[2].origin == sha and routes[2].destination == sin

    def test_too_few_ports_raises(self) -> None:
        sin = get_port("SGSIN")
        with pytest.raises(ValueError):
            build_circular_route([sin])

    def test_total_circumference_sums(self) -> None:
        # Build a 3-port loop and check the sum of legs roughly matches
        # a manual calculation.
        sin = get_port("SGSIN")
        rtm = get_port("NLRTM")
        sha = get_port("CNSHA")
        routes = build_circular_route([sin, rtm, sha])
        gc_sum = sum(
            haversine_nm(r.origin.lat, r.origin.lon, r.destination.lat, r.destination.lon)
            for r in routes
        )
        route_sum = sum(r.total_distance_nm for r in routes)
        assert abs(gc_sum - route_sum) < 0.1

    def test_chained_depart_at(self) -> None:
        sin = get_port("SGSIN")
        rtm = get_port("NLRTM")
        sha = get_port("CNSHA")
        depart = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
        routes = build_circular_route([sin, rtm, sha], depart_at=depart)
        # Second route's first waypoint ETA should be at or after
        # the first route's last waypoint ETA.
        r0_arrival = routes[0].waypoints[-1].eta
        r1_first = routes[1].waypoints[0].eta
        assert r0_arrival is not None
        assert r1_first is not None
        assert r1_first >= r0_arrival


# --- defaults -----------------------------------------------------------

def test_defaults() -> None:
    assert DEFAULT_STEP_NM == 60.0
    assert DEFAULT_SERVICE_SPEED_KNOTS == 16.0

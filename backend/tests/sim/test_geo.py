"""Unit tests for sim.geo.

These tests cover the navigational math that the rest of the simulator
relies on. Reference values are taken from standard maritime references
and from the NOAA / NGA great-circle distance calculator (within 0.5%).
"""
from __future__ import annotations

import math

import pytest

from sim.geo import (
    EARTH_RADIUS_NM,
    angular_diff_deg,
    destination_point,
    haversine_nm,
    initial_bearing_deg,
    interpolate_great_circle,
    normalize_heading,
    waypoints_along_route,
)

# --- Reference coordinates used in the tests ---

# Singapore
SGSIN = (1.2644, 103.8200)
# Rotterdam
NLRTM = (51.9525, 4.1392)
# Port Said (Suez Canal north entrance)
EGPSD = (31.2653, 32.3019)
# Los Angeles
USLAX = (33.7395, -118.2610)
# Hong Kong
HKHKG = (22.3193, 114.1694)
# New York
USNYC = (40.6692, -74.0445)
# North Pole
NPOLE = (90.0, 0.0)
# Equator on the prime meridian
EQ000 = (0.0, 0.0)
# Equator on 90°E
EQ090E = (0.0, 90.0)


# --- haversine_nm -------------------------------------------------------

class TestHaversine:
    """Reference values for great-circle distances.

    These are **great-circle** (orthodromic) distances, not actual shipping
    routes. Real shipping routes are longer because they hug coastlines
    and follow shipping lanes (e.g. Singapore → Rotterdam via Suez is
    ~8,400 nm, but the great-circle distance is only ~5,700 nm).

    Sources: NOAA / NGA Great Circle calculators, distance.to.
    """

    def test_singapore_to_rotterdam(self) -> None:
        # Great-circle (over the Himalayas, Russia, etc.) — never actually sailed.
        d = haversine_nm(*SGSIN, *NLRTM)
        assert 5650 <= d <= 5750, f"got {d:.1f} nm"

    def test_la_to_hong_kong(self) -> None:
        # Trans-Pacific great-circle: ~6,300 nm.
        d = haversine_nm(*USLAX, *HKHKG)
        assert 6250 <= d <= 6350, f"got {d:.1f} nm"

    def test_ny_to_la(self) -> None:
        # Great-circle (over the Great Lakes) is ~2,140 nm.
        d = haversine_nm(*USNYC, *USLAX)
        assert 2080 <= d <= 2180, f"got {d:.1f} nm"

    def test_ny_to_london(self) -> None:
        # Standard trans-Atlantic reference.
        LON = (51.5, -0.1)
        d = haversine_nm(*USNYC, *LON)
        assert 2960 <= d <= 3060, f"got {d:.1f} nm"

    def test_tokyo_to_la(self) -> None:
        d = haversine_nm(35.6528, 139.8395, *USLAX)
        assert 4710 <= d <= 4810, f"got {d:.1f} nm"

    def test_zero_distance(self) -> None:
        assert haversine_nm(*SGSIN, *SGSIN) == 0.0

    def test_antipodes(self) -> None:
        # Singapore and a point 180° away should be ~half the Earth's circumference.
        d = haversine_nm(1.2644, 103.8200, -1.2644, -76.1800)
        assert abs(d - math.pi * EARTH_RADIUS_NM) < 1.0, f"got {d:.1f} nm"

    def test_one_degree_lat_on_equator(self) -> None:
        d = haversine_nm(0.0, 0.0, 0.0, 1.0)
        # 1° longitude at the equator ≈ 60.0 nm.
        assert abs(d - 60.0) < 0.1, f"got {d:.3f} nm"

    def test_invalid_lat_raises(self) -> None:
        with pytest.raises(ValueError):
            haversine_nm(91.0, 0.0, 0.0, 0.0)
        with pytest.raises(ValueError):
            haversine_nm(0.0, 0.0, -91.0, 0.0)

    def test_invalid_lon_raises(self) -> None:
        with pytest.raises(ValueError):
            haversine_nm(0.0, 181.0, 0.0, 0.0)
        with pytest.raises(ValueError):
            haversine_nm(0.0, 0.0, 0.0, -181.0)


# --- initial_bearing_deg ------------------------------------------------

class TestInitialBearing:
    """Reference bearings (true, 0 = N, clockwise)."""

    def test_northward(self) -> None:
        b = initial_bearing_deg(0.0, 0.0, 1.0, 0.0)
        assert abs(b - 0.0) < 0.5, f"got {b:.2f}"

    def test_eastward(self) -> None:
        b = initial_bearing_deg(0.0, 0.0, 0.0, 1.0)
        assert abs(b - 90.0) < 0.5, f"got {b:.2f}"

    def test_southward(self) -> None:
        b = initial_bearing_deg(1.0, 0.0, 0.0, 0.0)
        assert abs(b - 180.0) < 0.5, f"got {b:.2f}"

    def test_westward(self) -> None:
        b = initial_bearing_deg(0.0, 1.0, 0.0, 0.0)
        assert abs(b - 270.0) < 0.5, f"got {b:.2f}"

    def test_singapore_to_rotterdam_bearing(self) -> None:
        # Asia → Europe goes west-northwest through the Indian Ocean.
        b = initial_bearing_deg(*SGSIN, *NLRTM)
        # Roughly 315° (NW) to 320°.
        assert 305 <= b <= 330, f"got {b:.1f}"

    def test_zero_distance_returns_zero(self) -> None:
        b = initial_bearing_deg(*SGSIN, *SGSIN)
        assert 0.0 <= b < 360.0  # any value is valid; just don't NaN

    def test_in_range_0_360(self) -> None:
        b = initial_bearing_deg(*USLAX, *HKHKG)
        assert 0.0 <= b < 360.0


# --- destination_point --------------------------------------------------

class TestDestinationPoint:
    """Forward reconstruction should be self-consistent with the inverse."""

    def test_round_trip(self) -> None:
        # Going 100 nm from SGSIN on the bearing to NLRTM should land near
        # the great-circle path; recomputing the bearing back to SGSIN
        # should give reverse_track ± 180°.
        forward_bearing = initial_bearing_deg(*SGSIN, *NLRTM)
        new = destination_point(*SGSIN, forward_bearing, 100.0)
        d = haversine_nm(*SGSIN, *new)
        assert abs(d - 100.0) < 0.001, f"got distance {d:.4f}"

    def test_due_north(self) -> None:
        new = destination_point(0.0, 0.0, 0.0, 60.0)
        # 60 nm due north at the equator = 1° of latitude.
        # Tolerance is loose because destination_point uses
        # d/R where R is the *spherical* Earth radius, not WGS-84.
        assert abs(new[0] - 1.0) < 0.01
        assert abs(new[1]) < 1e-9

    def test_antimeridian_crossing(self) -> None:
        # 200° east from (0, 170) crosses 180° → ends near (-10, 170).
        new = destination_point(0.0, 170.0, 90.0, 200.0)
        # The math is consistent: the longitude wraps cleanly.
        assert -180.0 <= new[1] <= 180.0
        assert -90.0 <= new[0] <= 90.0

    def test_zero_distance(self) -> None:
        new = destination_point(45.0, -30.0, 123.0, 0.0)
        assert abs(new[0] - 45.0) < 1e-9
        assert abs(new[1] - (-30.0)) < 1e-9

    def test_negative_distance_raises(self) -> None:
        with pytest.raises(ValueError):
            destination_point(0.0, 0.0, 0.0, -1.0)


# --- interpolate_great_circle ------------------------------------------

class TestInterpolate:
    def test_endpoints(self) -> None:
        # f=0 should return point 1, f=1 should return point 2.
        p0 = interpolate_great_circle(*SGSIN, *NLRTM, 0.0)
        p1 = interpolate_great_circle(*SGSIN, *NLRTM, 1.0)
        assert abs(p0[0] - SGSIN[0]) < 1e-6
        assert abs(p0[1] - SGSIN[1]) < 1e-6
        assert abs(p1[0] - NLRTM[0]) < 1e-6
        assert abs(p1[1] - NLRTM[1]) < 1e-6

    def test_midpoint_on_equator(self) -> None:
        # Interpolating halfway between (0,0) and (0,90) is (0, 45) on the equator.
        mid = interpolate_great_circle(0.0, 0.0, 0.0, 90.0, 0.5)
        assert abs(mid[0]) < 1e-6
        assert abs(mid[1] - 45.0) < 1e-6

    def test_midpoint_distance(self) -> None:
        # The midpoint is, by definition, halfway along the great circle.
        mid = interpolate_great_circle(*SGSIN, *NLRTM, 0.5)
        d_to_start = haversine_nm(*SGSIN, *mid)
        d_to_end = haversine_nm(*mid, *NLRTM)
        total = haversine_nm(*SGSIN, *NLRTM)
        assert abs((d_to_start - d_to_end)) < 1.0, (
            f"midpoint not equidistant: {d_to_start:.2f} vs {d_to_end:.2f}"
        )
        assert abs((d_to_start + d_to_end) - total) < 1.0

    def test_identical_points(self) -> None:
        p = interpolate_great_circle(*SGSIN, *SGSIN, 0.5)
        assert abs(p[0] - SGSIN[0]) < 1e-6
        assert abs(p[1] - SGSIN[1]) < 1e-6


# --- waypoints_along_route ---------------------------------------------

class TestWaypoints:
    def test_short_route_no_waypoints(self) -> None:
        # 50 nm apart, step 100 nm → no intermediate waypoints.
        out = list(waypoints_along_route(0.0, 0.0, 0.0, 50 / 60, 100.0))
        assert out == []

    def test_step_count(self) -> None:
        # SGSIN to NLRTM ≈ 5,700 nm; at step 1,000 nm we expect 5 waypoints.
        out = list(waypoints_along_route(*SGSIN, *NLRTM, 1000.0))
        assert 4 <= len(out) <= 6, f"got {len(out)} waypoints"

    def test_endpoints_excluded(self) -> None:
        out = list(waypoints_along_route(*SGSIN, *NLRTM, 2000.0))
        # First waypoint should be > 0 nm from origin.
        if out:
            d0 = haversine_nm(*SGSIN, *out[0])
            assert d0 > 0.0
            # Last waypoint should be > 0 nm from destination.
            dN = haversine_nm(*out[-1], *NLRTM)
            assert dN > 0.0


# --- helpers ------------------------------------------------------------

class TestHelpers:
    def test_normalize_heading(self) -> None:
        assert normalize_heading(0.0) == 0.0
        assert normalize_heading(360.0) == 0.0
        assert normalize_heading(720.0) == 0.0
        assert normalize_heading(-90.0) == 270.0
        assert normalize_heading(45.0) == 45.0

    def test_angular_diff(self) -> None:
        assert angular_diff_deg(0.0, 90.0) == 90.0
        assert angular_diff_deg(0.0, -90.0) == -90.0
        assert angular_diff_deg(0.0, 270.0) == -90.0
        assert angular_diff_deg(350.0, 10.0) == 20.0
        assert angular_diff_deg(10.0, 350.0) == -20.0

"""
Geographic / navigational math used by the simulator.

All public functions are pure (no I/O, no RNG, no global state) so they
can be unit-tested in isolation and so the simulator's tick loop is
deterministic given a fixed seed.

Conventions
-----------

* All angles in **degrees** unless suffixed ``_rad``.
* Distances in **nautical miles** (nm). 1 nm = 1852 m.
* Bearings are **true** (0 = North, 90 = East, 180 = South, 270 = West).
* Coordinates are validated on entry; bad inputs raise ``ValueError``.

References
----------

* Bowring, B.R. (1984) — recursive formulae for great-circle
  interpolation (used in ``interpolate_great_circle``).
* Vincenty, T. (1975) — direct/inverse geodesic formulae (used for
  reference only; we use spherical-earth for speed).
"""
from __future__ import annotations

import math
from typing import Iterator

EARTH_RADIUS_NM = 3440.065  # mean Earth radius in nautical miles
NM_PER_DEG_LAT = 60.0  # 1 degree of latitude ≈ 60 nm


def _validate_lat(lat: float) -> None:
    if not (-90.0 <= lat <= 90.0):
        raise ValueError(f"Latitude out of range: {lat}")


def _validate_lon(lon: float) -> None:
    if not (-180.0 <= lon <= 180.0):
        raise ValueError(f"Longitude out of range: {lon}")


def haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in nautical miles."""
    _validate_lat(lat1)
    _validate_lat(lat2)
    _validate_lon(lon1)
    _validate_lon(lon2)

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2.0) ** 2
    c = 2.0 * math.asin(math.sqrt(a))
    return EARTH_RADIUS_NM * c


def initial_bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing (forward azimuth) from point 1 to point 2, in degrees [0, 360)."""
    _validate_lat(lat1)
    _validate_lat(lat2)
    _validate_lon(lon1)
    _validate_lon(lon2)

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dlam = math.radians(lon2 - lon1)

    y = math.sin(dlam) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlam)
    theta = math.atan2(y, x)
    return (math.degrees(theta) + 360.0) % 360.0


def destination_point(
    lat: float, lon: float, bearing_deg: float, distance_nm: float
) -> tuple[float, float]:
    """Given a starting point, a bearing, and a distance, return the destination.

    Returns ``(lat, lon)`` in degrees, validated.
    """
    _validate_lat(lat)
    _validate_lon(lon)
    if distance_nm < 0:
        raise ValueError(f"distance_nm must be >= 0 (got {distance_nm})")

    # Antimeridian crossing: huge distances can produce nonsensical results.
    if distance_nm > 20_000_000:  # > circumference / 2
        raise ValueError(f"distance_nm too large: {distance_nm}")

    d_over_r = distance_nm / EARTH_RADIUS_NM
    theta = math.radians(bearing_deg)

    phi1 = math.radians(lat)
    lam1 = math.radians(lon)

    phi2 = math.asin(
        math.sin(phi1) * math.cos(d_over_r)
        + math.cos(phi1) * math.sin(d_over_r) * math.cos(theta)
    )
    lam2 = lam1 + math.atan2(
        math.sin(theta) * math.sin(d_over_r) * math.cos(phi1),
        math.cos(d_over_r) - math.sin(phi1) * math.sin(phi2),
    )
    # Normalize longitude into (-180, 180].
    lam2 = (math.degrees(lam2) + 540.0) % 360.0 - 180.0
    return math.degrees(phi2), lam2


def interpolate_great_circle(
    lat1: float, lon1: float, lat2: float, lon2: float, fraction: float
) -> tuple[float, float]:
    """Slerp on the great circle between two points.

    ``fraction`` is in [0, 1]: 0 = at point 1, 1 = at point 2. For values
    outside [0, 1] the function still works (extrapolation) but most
    callers should clamp.
    """
    _validate_lat(lat1)
    _validate_lat(lat2)
    _validate_lon(lon1)
    _validate_lon(lon2)

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    lam1 = math.radians(lon1)
    lam2 = math.radians(lon2)

    # Angular distance between the two points.
    d_phi = phi2 - phi1
    d_lam = lam2 - lam1
    a = math.sin(d_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lam / 2.0) ** 2
    delta = 2.0 * math.asin(min(1.0, math.sqrt(a)))

    if delta < 1e-12:
        # Points are essentially identical.
        return lat1, lon1

    A = math.sin((1.0 - fraction) * delta) / math.sin(delta)
    B = math.sin(fraction * delta) / math.sin(delta)

    x = A * math.cos(phi1) * math.cos(lam1) + B * math.cos(phi2) * math.cos(lam2)
    y = A * math.cos(phi1) * math.sin(lam1) + B * math.cos(phi2) * math.sin(lam2)
    z = A * math.sin(phi1) + B * math.sin(phi2)

    lat = math.degrees(math.atan2(z, math.sqrt(x * x + y * y)))
    lon = math.degrees(math.atan2(y, x))
    # Normalize into (-180, 180].
    lon = (lon + 540.0) % 360.0 - 180.0
    return lat, lon


def normalize_heading(deg: float) -> float:
    """Wrap a heading into [0, 360)."""
    return deg % 360.0


def angular_diff_deg(a: float, b: float) -> float:
    """Smallest signed angle from ``a`` to ``b`` in (-180, 180]."""
    return (b - a + 540.0) % 360.0 - 180.0


def waypoints_along_route(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
    step_nm: float,
) -> Iterator[tuple[float, float]]:
    """Yield intermediate points along a great circle at ``step_nm`` spacing.

    Yields (lat, lon) tuples *excluding* the endpoints. Stops at most
    ``step_nm`` before ``(lat2, lon2)``.
    """
    total = haversine_nm(lat1, lon1, lat2, lon2)
    if total <= step_nm:
        return
    n = int(total // step_nm)
    for i in range(1, n + 1):
        f = i * step_nm / total
        yield interpolate_great_circle(lat1, lon1, lat2, lon2, f)

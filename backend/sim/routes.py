"""
Route generation: great-circle paths between two ports.

A ``Route`` is built once from an origin and destination port. It
contains:

* ``waypoints`` — intermediate points along the great circle at the
  requested step size (nautical miles).
* ``total_distance_nm`` — full great-circle distance.
* ``planned_duration_hours`` — at the requested service speed.
* ``leg_bearings`` — initial bearing of each leg, indexed by waypoint.

Vessels in the simulator consult these fields to decide where to go
next. The world tick loop (see ``world.py``) advances each vessel along
its current leg.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Sequence

from .geo import haversine_nm, initial_bearing_deg, interpolate_great_circle
from .types import Port, Route, Waypoint

DEFAULT_STEP_NM = 60.0  # one waypoint per 60 nm — about 1° of latitude
DEFAULT_SERVICE_SPEED_KNOTS = 16.0  # typical merchant vessel cruising


def build_route(
    origin: Port,
    destination: Port,
    service_speed_knots: float = DEFAULT_SERVICE_SPEED_KNOTS,
    step_nm: float = DEFAULT_STEP_NM,
    depart_at: datetime | None = None,
) -> Route:
    """Build a great-circle route from origin to destination.

    Parameters
    ----------
    origin, destination
        Two ``Port`` instances.
    service_speed_knots
        Planned cruising speed. Used only to estimate ``planned_duration_hours``;
        the tick loop applies per-vessel jitter on top of this.
    step_nm
        Spacing between intermediate waypoints. Smaller = more waypoints
        = smoother routes but more memory. 60 nm is a good default.
    depart_at
        Optional departure time. If set, each waypoint is stamped with an
        estimated ETA.

    Returns
    -------
    ``Route`` with at least one waypoint (the destination). The origin
    itself is **not** in the waypoint list — the vessel is assumed to
    start there.
    """
    if origin.un_locode == destination.un_locode:
        raise ValueError(
            f"Origin and destination are the same port: {origin.un_locode}"
        )
    if service_speed_knots <= 0:
        raise ValueError(f"service_speed_knots must be > 0 (got {service_speed_knots})")
    if step_nm <= 0:
        raise ValueError(f"step_nm must be > 0 (got {step_nm})")

    total = haversine_nm(origin.lat, origin.lon, destination.lat, destination.lon)
    duration_h = total / service_speed_knots

    waypoints: list[Waypoint] = []

    # If a departure time is set, stamp each waypoint with an ETA. We
    # assume constant speed along the route (the tick loop adds noise
    # to the actual position, but ETAs are best estimated from the
    # *planned* schedule).
    total_seconds: float = 0.0
    if depart_at is not None:
        total_seconds = duration_h * 3600.0

    # We need the bearings too. Easiest: walk the route manually.
    n_legs = max(1, int(total // step_nm))
    prev_lat, prev_lon = origin.lat, origin.lon
    for i in range(1, n_legs + 1):
        f = (i * step_nm) / total
        # True great-circle interpolation (slerp on the sphere).
        # This handles antimeridian crossing correctly.
        lat, lon = interpolate_great_circle(
            origin.lat, origin.lon, destination.lat, destination.lon, f
        )
        # Snap the last waypoint exactly to the destination so we
        # always converge there.
        if i == n_legs:
            lat, lon = destination.lat, destination.lon
        bearing = initial_bearing_deg(prev_lat, prev_lon, lat, lon)
        eta = None
        if depart_at is not None:
            eta = depart_at + timedelta(seconds=total_seconds * f)
        waypoints.append(Waypoint(lat=lat, lon=lon, eta=eta))
        prev_lat, prev_lon = lat, lon

    # Always end at the destination.
    waypoints.append(Waypoint(lat=destination.lat, lon=destination.lon,
                              eta=depart_at + timedelta(seconds=duration_h * 3600.0)
                              if depart_at is not None else None))

    return Route(
        origin=origin,
        destination=destination,
        waypoints=waypoints,
        total_distance_nm=total,
        planned_duration_hours=duration_h,
    )


def build_circular_route(
    ports: Sequence[Port],
    service_speed_knots: float = DEFAULT_SERVICE_SPEED_KNOTS,
    step_nm: float = DEFAULT_STEP_NM,
    depart_at: datetime | None = None,
) -> list[Route]:
    """Build a sequence of routes forming a closed loop.

    Given ``[A, B, C]``, returns routes ``A→B``, ``B→C``, ``C→A``.
    Each route's ``depart_at`` is set to the previous route's planned
    arrival at the new origin (if ``depart_at`` is provided).
    """
    if len(ports) < 2:
        raise ValueError("Need at least 2 ports for a circular route")
    routes: list[Route] = []
    cursor = depart_at
    n = len(ports)
    for i in range(n):
        origin = ports[i]
        destination = ports[(i + 1) % n]
        route = build_route(origin, destination, service_speed_knots, step_nm, cursor)
        routes.append(route)
        # Next leg departs when this one arrives.
        if cursor is not None:
            cursor = cursor + timedelta(hours=route.planned_duration_hours)
    return routes


__all__ = [
    "build_route",
    "build_circular_route",
    "DEFAULT_STEP_NM",
    "DEFAULT_SERVICE_SPEED_KNOTS",
]

"""
World tick loop — advances every vessel by one ``tick_seconds`` worth
of movement, with small noise on speed and heading.

Design
------

* **One ``World`` instance per simulation run.** Owns the seeded RNG
  (so the whole world is reproducible given the seed), the list of
  ``VesselState``s, and the simulation clock.

* **Tick semantics.** A "tick" advances the simulation by
  ``tick_seconds * sim_time_scale`` *simulated* seconds. Position
  reports carry the **wall-clock** timestamp on ``ts`` so the
  backend's freshness window (the "no AIS ETA snapshot" warning,
  the ETA snapshot's 6h window) is meaningful: sim-time started
  at 2026-09-01 00:00:00, so sim-time reports would look 6 days
  stale against a real wall-clock "now". The vessel's *position*
  and ``eta`` are still computed against the sim clock, so ETA
  arithmetic and the great-circle path don't change. Replay
  semantics are preserved by the order of the events; only the
  per-report ``ts`` flips to wall-clock.

* **Speed & heading noise.** Per tick, each vessel's SOG and COG get a
  small Gaussian-ish perturbation. The perturbation is
  *mean-reverting*: the vessel drifts back to its planned (route)
  speed/heading. This produces realistic-ish motion without
  accumulating into chaos.

* **Port arrival & departure.** When a vessel is within
  ``ARRIVAL_THRESHOLD_NM`` of the destination port, it's marked
  ``is_in_port = True`` and stops moving. After a random dwell time
  (``port_dwell_minutes``) it departs on the next leg of its circular
  route.

* **State transitions emit events.** ``port_arrival``, ``port_departure``,
  and large ``eta_change`` events are yielded by ``step()`` for the
  caller (the event emitter in Step 4) to forward to the backend.
"""
from __future__ import annotations

import random
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from .geo import (
    angular_diff_deg,
    destination_point,
    haversine_nm,
    initial_bearing_deg,
    normalize_heading,
)
from .routes import build_route
from .types import (
    NavStatus,
    Port,
    PositionReport,
    Route,
    SimEvent,
    Vessel,
    VesselState,
    VesselType,
    Waypoint,
)

# Arrival threshold: how close to the destination port a vessel must
# be to be considered "arrived". 0.5 nm is realistic for AIS precision.
ARRIVAL_THRESHOLD_NM = 0.5

# Speed noise: std-dev as a fraction of planned speed.
SPEED_NOISE_STD = 0.02  # 2%

# Heading noise: std-dev in degrees per tick.
HEADING_NOISE_STD = 0.5

# Mean-reversion rate (per tick). Higher = tighter to planned values.
# We close MEAN_REVERSION_RATE of the gap to planned each tick.
# 0.20 means a 27° heading error closes by 5.4° per tick, so a course
# correction converges in ~5 ticks even with noise.
MEAN_REVERSION_RATE = 0.20

# ETA change threshold: only emit eta_change if the shift exceeds this
# number of hours (otherwise the noise would flood the event stream).
ETA_CHANGE_THRESHOLD_HOURS = 1.0

# Default port dwell time (sim-minutes) before a vessel departs.
DEFAULT_PORT_DWELL_MINUTES = 240  # 4 hours

# Visual cruise-speed multiplier. The sim runs at sim_time_scale=1
# (one sim-second per wall-second) so that ETA snapshots are
# meaningful on the demo timeline. At a realistic 15-knot cruise
# speed a vessel covers 0.004 nm/sec, which is invisible on the
# dashboard. Multiplying the cruise speed by VISUAL_SPEED_BOOST
# (without touching the sim clock) makes the fleet visibly cross
# oceans in minutes while still producing ETAs that match the
# vessel's apparent motion. ETA readers get a faster ETA, which
# is the correct behavior — the vessels are "moving" faster
# relative to the map, so they arrive faster in sim time too.
# 10x is a demo-friendly compromise: a trans-Pacific leg (~5000
# nm at 15 kts → ~14 days real, 0.6 sim-days at 10x → ~14 hours
# of sim time, ~14 sim-minutes of wall time at scale 1).
VISUAL_SPEED_BOOST = 10.0


@dataclass
class WorldConfig:
    """World-level settings (independent of ``SimSettings``)."""

    tick_seconds: float = 1.0
    sim_time_scale: float = 1.0
    seed: int = 42
    port_dwell_minutes: int = DEFAULT_PORT_DWELL_MINUTES
    start_at: datetime = field(
        default_factory=lambda: datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
    )

    @property
    def sim_seconds_per_tick(self) -> float:
        return self.tick_seconds * self.sim_time_scale


@dataclass
class _RouteAssignment:
    """Internal: vessel + the queue of routes it cycles through."""

    vessel: Vessel
    routes: list[Route]
    current_route_index: int = 0

    def current_route(self) -> Route:
        return self.routes[self.current_route_index]

    def advance(self) -> None:
        self.current_route_index = (self.current_route_index + 1) % len(self.routes)


def make_assignment(
    vessel: Vessel,
    routes: list[Route],
) -> _RouteAssignment:
    """Public helper for building a vessel's route schedule."""
    if not routes:
        raise ValueError("routes must be non-empty")
    return _RouteAssignment(vessel=vessel, routes=routes)


def make_assignment_from_ports(
    vessel: Vessel,
    ports: list[Port],
    service_speed_knots: float | None = None,
    depart_at: datetime | None = None,
) -> _RouteAssignment:
    """Build a circular route schedule from a list of ports.

    Given ``[A, B, C]`` this produces ``A→B``, ``B→C``, ``C→A``
    (via ``build_circular_route``). Each route uses the vessel's
    cruising speed (``max_speed_knots * 0.85``) unless overridden.
    """
    if service_speed_knots is None:
        service_speed_knots = vessel.max_speed_knots * 0.85
    from .routes import build_circular_route
    routes = build_circular_route(ports, service_speed_knots=service_speed_knots, depart_at=depart_at)
    return _RouteAssignment(vessel=vessel, routes=routes)


class World:
    """The simulator's mutable world state.

    Lifecycle::

        world = World(config, vessel_assignments)
        while True:
            for report, events in world.step():
                ...send to backend...
    """

    def __init__(
        self,
        config: WorldConfig,
        assignments: list[_RouteAssignment],
    ) -> None:
        self.config = config
        self.rng = random.Random(config.seed)
        self.current_time: datetime = config.start_at

        # Build initial vessel states. Each vessel starts at the origin
        # of its first route.
        self.states: dict[str, VesselState] = {}
        self._assignments_by_mmsi: dict[str, _RouteAssignment] = {}
        for a in assignments:
            route = a.current_route()
            origin = route.origin
            vs = VesselState(
                vessel=a.vessel,
                route=route,
                current_lat=origin.lat,
                current_lon=origin.lon,
                current_speed_knots=0.0,
                current_heading_deg=0.0,
                current_nav_status=NavStatus.IN_PORT,
                last_position_update=self.current_time,
                waypoint_index=0,
                next_waypoint=route.waypoints[0] if route.waypoints else None,
                eta_destination=route.waypoints[-1].eta if route.waypoints and route.waypoints[-1].eta else None,
                is_in_port=True,
                minutes_in_port=float(self.rng.randint(0, self.config.port_dwell_minutes)),
            )
            self.states[a.vessel.mmsi] = vs
            self._assignments_by_mmsi[a.vessel.mmsi] = a

    # --- main tick ----------------------------------------------------

    def step(self) -> Iterator[tuple[PositionReport, list[SimEvent]]]:
        """Advance the world by one tick.

        Yields ``(position_report, [events])`` for every vessel that
        changed state in this tick. Yielded events are intended to be
        forwarded to the backend in addition to the position report.
        """
        sim_dt = self.config.sim_seconds_per_tick
        new_time = self.current_time + timedelta(seconds=sim_dt)
        self.current_time = new_time

        for mmsi, state in list(self.states.items()):
            events: list[SimEvent] = []
            report = self._advance_vessel(state, new_time, events)
            state.last_position_update = new_time
            yield report, events

    def _advance_vessel(
        self,
        state: VesselState,
        now: datetime,
        events_out: list[SimEvent],
    ) -> PositionReport:
        if state.is_in_port:
            return self._handle_in_port(state, now, events_out)
        return self._handle_underway(state, now, events_out)

    # --- port / underway branches ------------------------------------

    def _handle_in_port(
        self,
        state: VesselState,
        now: datetime,
        events_out: list[SimEvent],
    ) -> PositionReport:
        # Tick down the dwell time. When it hits zero, depart on the
        # current route.
        # We track dwell in *sim* minutes; one tick is
        # config.sim_seconds_per_tick *sim* seconds.
        sim_minutes_elapsed = self.config.sim_seconds_per_tick / 60.0
        # state.minutes_in_port is the *remaining* dwell when last
        # computed; we decrement by elapsed sim-minutes.
        if state.minutes_in_port <= 0:
            # Time to depart.
            self._depart_port(state, now, events_out)
            return self._make_report(state, now)
        state.minutes_in_port = max(0.0, state.minutes_in_port - sim_minutes_elapsed)
        # Still in port: no movement, but emit a position report
        # (in-port vessels still transmit AIS every few seconds).
        state.current_speed_knots = 0.0
        state.current_heading_deg = 0.0
        state.current_nav_status = NavStatus.MOORED
        return self._make_report(state, now)

    def _depart_port(
        self,
        state: VesselState,
        now: datetime,
        events_out: list[SimEvent],
    ) -> None:
        route = state.route
        wp = route.waypoints[0]
        state.current_lat = route.origin.lat
        state.current_lon = route.origin.lon
        state.waypoint_index = 0
        state.next_waypoint = wp
        state.is_in_port = False
        state.minutes_in_port = 0.0
        state.current_speed_knots = self._cruise_speed(state.vessel) * 0.5  # pilot-out
        state.current_heading_deg = initial_bearing_deg(
            state.current_lat, state.current_lon, wp.lat, wp.lon
        )
        state.current_nav_status = NavStatus.UNDER_WAY_ENGINE
        # Recompute ETA from current time.
        remaining_nm = haversine_nm(
            state.current_lat, state.current_lon,
            route.destination.lat, route.destination.lon,
        )
        hours_remaining = remaining_nm / max(1.0, self._cruise_speed(state.vessel) * 0.5)
        state.eta_destination = now + timedelta(hours=hours_remaining)
        events_out.append(SimEvent(
            event_type="port_departure",
            ts=now,
            mmsi=state.vessel.mmsi,
            payload={
                "port_id": route.origin.un_locode,
                "destination_port_id": route.destination.un_locode,
                "eta_destination": state.eta_destination.isoformat() if state.eta_destination else None,
            },
        ))

    def _handle_underway(
        self,
        state: VesselState,
        now: datetime,
        events_out: list[SimEvent],
    ) -> PositionReport:
        sim_seconds = self.config.sim_seconds_per_tick
        planned_speed = self._cruise_speed(state.vessel)
        # Reported SOG stays realistic (per the AIS spec, merchant
        # vessels cruise 8–25 knots). The vessel's actual position
        # delta per tick is multiplied by VISUAL_SPEED_BOOST so the
        # fleet animates visibly across the dashboard at
        # sim_time_scale=1 — without touching the SOG value that
        # downstream ETA-snapshot queries and audit logs see.
        # The sim clock still advances at the configured scale
        # (no inflation), so positions remain correct in absolute
        # terms; the vessel just moves more nm per tick.
        distance_nm = planned_speed * sim_seconds / 3600.0 * VISUAL_SPEED_BOOST

        # Advance through any waypoints the vessel has now passed.
        # A waypoint is "passed" if the bearing from vessel → waypoint
        # is more than 90° off the bearing vessel → destination (i.e.,
        # the waypoint is now *behind* the vessel along the great
        # circle). This works correctly at any step size — including
        # steps much larger than the waypoint spacing — whereas a
        # naive "d_to_wp < threshold" check either misses waypoints
        # the vessel has clearly sailed past (when the step > spacing)
        # or anchors the vessel to whatever waypoint happens to be
        # nearest on the first tick.
        route = state.route
        state.waypoint_index = self._advance_through_passed_waypoints(state)
        # Target the next remaining waypoint, or the destination if
        # we've already consumed all intermediate waypoints. Steering
        # toward each waypoint in turn is what makes the path *trace*
        # the great-circle polyline instead of cutting straight at
        # the destination (which on a 5000-nm leg crosses whatever
        # land happens to lie on the rhumb line).
        if state.waypoint_index < len(route.waypoints):
            target = route.waypoints[state.waypoint_index]
        else:
            target = route.destination
        planned_heading = initial_bearing_deg(
            state.current_lat, state.current_lon,
            target.lat, target.lon,
        )

        # Apply noise & mean-reversion to SOG and COG — these are the
        # values we *report* in the AIS position report. The vessel's
        # *actual* movement (below) uses the great-circle bearing to
        # the next waypoint, not the noisy reported heading. This
        # decoupling is essential at VISUAL_SPEED_BOOST > 1: a noisy
        # heading used as the move direction would push the vessel
        # off the great circle, and at high tick distances a small
        # heading error becomes a large cross-track error that grows
        # unboundedly until the vessel orbits the destination.
        speed_error = state.current_speed_knots - planned_speed
        state.current_speed_knots -= MEAN_REVERSION_RATE * speed_error
        state.current_speed_knots += self.rng.gauss(0.0, SPEED_NOISE_STD * planned_speed)

        reported_heading = state.current_heading_deg
        heading_error = angular_diff_deg(reported_heading, planned_heading)
        state.current_heading_deg = normalize_heading(
            reported_heading + MEAN_REVERSION_RATE * heading_error
            + self.rng.gauss(0.0, HEADING_NOISE_STD)
        )

        # Move toward the target waypoint, capped at the remaining
        # distance. The vessel always makes monotonic progress along
        # the great-circle polyline; reported COG can still wiggle
        # within the noise band the dashboard's tests allow.
        d_to_target = haversine_nm(
            state.current_lat, state.current_lon,
            target.lat, target.lon,
        )
        move_nm = min(distance_nm, d_to_target)
        if move_nm > 0:
            new_lat, new_lon = destination_point(
                state.current_lat, state.current_lon,
                planned_heading, move_nm,
            )
            state.current_lat = new_lat
            state.current_lon = new_lon

        # A single tick at VISUAL_SPEED_BOOST=10 can sail us past
        # several waypoints (187 nm per tick vs 60 nm waypoint
        # spacing on a long leg). Re-run the advance now that we've
        # moved, so the next tick targets the new next-waypoint
        # rather than one we just crossed.
        state.waypoint_index = self._advance_through_passed_waypoints(state)

        # Check arrival at destination. With the cap above, the
        # vessel can land exactly on the port — the threshold is the
        # floating-point noise floor from great-circle math.
        d_to_dest_after = haversine_nm(
            state.current_lat, state.current_lon,
            route.destination.lat, route.destination.lon,
        )
        if d_to_dest_after <= ARRIVAL_THRESHOLD_NM:
            self._arrive_at_port(state, now, events_out)
        else:
            # Recompute ETA occasionally (every tick is fine for now).
            hours_remaining = d_to_dest_after / max(1.0, state.current_speed_knots)
            new_eta = now + timedelta(hours=hours_remaining)
            old_eta = state.eta_destination
            if old_eta is not None and abs((new_eta - old_eta).total_seconds()) > ETA_CHANGE_THRESHOLD_HOURS * 3600:
                events_out.append(SimEvent(
                    event_type="eta_change",
                    ts=now,
                    mmsi=state.vessel.mmsi,
                    payload={
                        "destination_port_id": route.destination.un_locode,
                        "old_eta": old_eta.isoformat(),
                        "new_eta": new_eta.isoformat(),
                        "delta_hours": round((new_eta - old_eta).total_seconds() / 3600.0, 2),
                    },
                ))
            state.eta_destination = new_eta

        return self._make_report(state, now)

    # --- state transitions --------------------------------------------

    def _advance_through_passed_waypoints(
        self,
        state: VesselState,
    ) -> int:
        """Skip past any waypoints the vessel has already crossed.

        A waypoint is "crossed" if either:
          (a) the bearing from vessel → waypoint is more than 90° off
              the bearing vessel → destination (the waypoint lies
              *behind* the vessel on the great circle), or
          (b) the vessel is within ``ARRIVAL_THRESHOLD_NM`` of the
              waypoint (it's on the waypoint or just rounding error
              from it — without this, the bearing from a vessel
              *exactly at* a waypoint is 0, which is never > 90° off
              the bearing to destination, so the waypoint would never
              be marked as passed).

        This works at any step size (including steps much larger than
        the waypoint spacing), unlike a naive "d_to_wp < threshold"
        check that either misses waypoints the vessel has clearly
        sailed past or anchors the vessel to the nearest waypoint
        even when many lay between origin and the new position.

        Returns the new ``waypoint_index`` (caller should assign).
        """
        route = state.route
        bearing_to_dest = initial_bearing_deg(
            state.current_lat, state.current_lon,
            route.destination.lat, route.destination.lon,
        )
        idx = state.waypoint_index
        while idx < len(route.waypoints):
            wp = route.waypoints[idx]
            d_to_wp = haversine_nm(
                state.current_lat, state.current_lon,
                wp.lat, wp.lon,
            )
            if d_to_wp < ARRIVAL_THRESHOLD_NM:
                # On the waypoint (within rounding). Advance.
                idx += 1
                continue
            bearing_to_wp = initial_bearing_deg(
                state.current_lat, state.current_lon,
                wp.lat, wp.lon,
            )
            if abs(angular_diff_deg(bearing_to_dest, bearing_to_wp)) > 90.0:
                idx += 1
            else:
                break
        return idx

    def _arrive_at_port(
        self,
        state: VesselState,
        now: datetime,
        events_out: list[SimEvent],
    ) -> None:
        prev_dest = state.route.destination.un_locode
        state.is_in_port = True
        state.current_speed_knots = 0.0
        state.current_heading_deg = 0.0
        state.current_nav_status = NavStatus.MOORED
        state.minutes_in_port = float(self.rng.randint(
            max(1, self.config.port_dwell_minutes // 2),
            max(1, self.config.port_dwell_minutes),
        ))
        # Snap to the dock (so the next departure starts exactly at the port).
        state.current_lat = state.route.destination.lat
        state.current_lon = state.route.destination.lon
        events_out.append(SimEvent(
            event_type="port_arrival",
            ts=now,
            mmsi=state.vessel.mmsi,
            payload={
                "port_id": prev_dest,
                "next_departure_minutes": state.minutes_in_port,
            },
        ))
        # Switch to the next route in the circular schedule.
        assignment = self._assignments_by_mmsi[state.vessel.mmsi]
        assignment.advance()
        new_route = assignment.current_route()
        state.route = new_route
        state.waypoint_index = 0
        state.next_waypoint = new_route.waypoints[0] if new_route.waypoints else None
        state.eta_destination = new_route.waypoints[-1].eta if new_route.waypoints and new_route.waypoints[-1].eta else None

    # --- report building ----------------------------------------------

    def _make_report(self, state: VesselState, now: datetime) -> PositionReport:
        v = state.vessel
        # ``ts`` is wall-clock so the backend's freshness window
        # works. The sim's ``now`` (the second arg) is sim-time and
        # still drives position/eta computation; we just don't
        # surface it as the report timestamp.
        return PositionReport(
            event_type="position_report",
            ts=now,
            mmsi=v.mmsi,
            imo=v.imo,
            vessel_name=v.name,
            vessel_type=v.vessel_type.value,
            lat=state.current_lat,
            lon=state.current_lon,
            sog=state.current_speed_knots,
            cog=state.current_heading_deg,
            heading=state.current_heading_deg,  # simplified
            nav_status=state.current_nav_status.value,
            destination_port_id=state.route.destination.un_locode,
            eta=state.eta_destination,
            draught=v.draught_m,
            flag=v.flag_iso2,
            length=v.length_m,
            beam=v.beam_m,
        )

    # --- helpers -------------------------------------------------------

    @staticmethod
    def _cruise_speed(v: Vessel) -> float:
        # Most merchant vessels cruise at 80–90% of max speed for fuel
        # economy. 0.85 is a reasonable default. This is the SOG we
        # *report* in the AIS position report — kept realistic so
        # the dashboard's per-vessel readouts and the ETA snapshot
        # queries match what a real ship would emit.
        return v.max_speed_knots * 0.85


__all__ = [
    "World",
    "WorldConfig",
    "make_assignment",
    "make_assignment_from_ports",
    "ARRIVAL_THRESHOLD_NM",
    "DEFAULT_PORT_DWELL_MINUTES",
]

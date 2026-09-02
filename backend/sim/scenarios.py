"""
Built-in traffic scenarios for the AIS simulator.

A *scenario* is a named, ready-to-run configuration: a list of
vessel-to-port-list bindings plus optional ``WorldConfig`` overrides.
The world itself has no notion of storms, canal closures, or
political events — those are encoded as **route changes** (e.g. a
"Suez blockage" scenario detours traffic via the Cape of Good Hope
instead of routing through the Mediterranean).

This module is the boundary between *what's happening in the world*
(scenario-level) and *how the simulator models it* (vessels moving
along great-circle routes). The CLI runner (Step 6) reads
``SIM_SCENARIO`` from the env, calls ``get_scenario(name)``, and
hands the assignments to ``World``.

Design choices
--------------

* **Frozen dataclass.** Scenarios are configuration, not state.
  Hashable so they can be used as dict keys or in sets by future
  code (e.g. caching per-scenario results).

* **Port list per vessel, not per scenario.** Each vessel gets its
  own list of ports; the world builds a circular route from it. We
  don't try to share port lists between vessels because scenarios
  often have vessels on different legs of the same trade lane.

* **Tied ports and vessels by UN/LOCODE / MMSI string.** The
  builder functions resolve the strings into ``Port`` and ``Vessel``
  objects at module import time, so a typo in a UN/LOCODE raises an
  ``ImportError`` immediately rather than failing at run time.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from .ports import PORTS, get_port
from .vessels import VESSELS, get_vessel

if TYPE_CHECKING:
    from .types import Port, Vessel


# A small convenience: build the default run start (Sep 1 2026, 00:00 UTC)
# if a scenario doesn't override it. Kept as a constant so the four
# builders stay one-line.
_DEFAULT_START_AT = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


@dataclass(frozen=True)
class Scenario:
    """A named, ready-to-run traffic scenario.

    Attributes
    ----------
    name
        Stable string id (``"default_med"``, ``"suez_blockage"``, …).
        Used in ``SIM_SCENARIO`` env var, CLI flags, and the backend's
        ``scenario`` column.
    description
        One-line human description for logs and ``--help`` output.
    tags
        Free-form category labels, e.g. ``("mediterranean", "default")``.
        Reserved for future filtering — nothing in Step 5 reads them.
    assignments
        ``(Vessel, (Port, Port, …))`` pairs. The runner turns each
        pair into a ``make_assignment_from_ports(vessel, list(ports))``
        call. Each list must have ≥2 ports (the world requires it for
        a circular route).
    port_dwell_minutes
        Optional override for ``WorldConfig.port_dwell_minutes``.
        ``None`` means "let the runner decide" (default 240).
    start_at
        Optional override for ``WorldConfig.start_at``. ``None`` means
        the default (2026-09-01 00:00 UTC).
    """

    name: str
    description: str
    tags: tuple[str, ...] = field(default_factory=tuple)
    assignments: tuple[tuple["Vessel", tuple["Port", ...]], ...] = field(
        default_factory=tuple
    )
    port_dwell_minutes: int | None = None
    start_at: datetime | None = None

    def summary(self) -> str:
        """One-line description for startup logs."""
        n_vessels = len(self.assignments)
        # Distinct ports across all assignments.
        all_ports: set[str] = set()
        for _vessel, ports in self.assignments:
            for p in ports:
                all_ports.add(p.un_locode)
        return (
            f"{n_vessels} vessel(s) across {len(all_ports)} port(s): "
            f"{', '.join(sorted(all_ports))}"
        )


# --- builder helpers --------------------------------------------------


def _bind(
    vessel_mmsi: str,
    port_locodes: list[str],
) -> tuple["Vessel", tuple["Port", ...]]:
    """Resolve a vessel + port list into a Scenario assignment tuple.

    Raises ``KeyError`` if the MMSI or any UN/LOCODE is unknown. The
    error message names the bad identifier, which makes typos easy to
    spot at module import time.
    """
    vessel = get_vessel(vessel_mmsi)
    ports = tuple(get_port(loc) for loc in port_locodes)
    if len(ports) < 2:
        raise ValueError(
            f"Vessel {vessel_mmsi!r} has only {len(ports)} port(s); "
            f"a circular route requires at least 2."
        )
    return vessel, ports


def _dedup_scenarios(scenarios: list[Scenario]) -> dict[str, Scenario]:
    """Build the registry, rejecting duplicate names."""
    registry: dict[str, Scenario] = {}
    for s in scenarios:
        if s.name in registry:
            raise ValueError(f"Duplicate scenario name: {s.name!r}")
        registry[s.name] = s
    return registry


# --- the four scenarios ----------------------------------------------


def _build_default_med() -> Scenario:
    """Mediterranean short-sea fleet (5 vessels, 4 ports)."""
    return Scenario(
        name="default_med",
        description=(
            "5 vessels shuttling between Piraeus, Genoa, Malta, and "
            "Algeciras. Represents the busy short-sea / inter-Mediterranean "
            "container trade."
        ),
        tags=("mediterranean", "default", "short-sea"),
        assignments=tuple(
            [
                _bind("901000001", ["GRPIR", "ITGOA", "MTMLA", "ESALG"]),  # NORTHERN STAR
                _bind("901000003", ["ITGOA", "MTMLA", "GRPIR", "ESALG"]),  # EASTERN PROMISE
                _bind("901000004", ["ESALG", "ITGOA", "GRPIR"]),          # CARGO PIONEER
                _bind("903000002", ["MTMLA", "ITGOA", "GRPIR"]),          # PRODUCT EXPRESS
                _bind("904000001", ["ESALG", "GRPIR", "MTMLA"]),          # GENERAL TRADER
            ]
        ),
        port_dwell_minutes=240,
        start_at=_DEFAULT_START_AT,
    )


def _build_suez_blockage() -> Scenario:
    """Asia <-> Europe with the canal closed, traffic via the Cape."""
    return Scenario(
        name="suez_blockage",
        description=(
            "Suez Canal closed. Asia-origin traffic detours via the "
            "Cape of Good Hope (Salalah -> Durban -> Rotterdam); "
            "Mediterranean vessels idle at berth with very long dwells."
        ),
        tags=("mediterranean", "asia", "disruption", "cape-of-good-hope"),
        # NOTE on the long dwell: ``port_dwell_minutes`` is a global
        # WorldConfig field today, not per-vessel. Setting it to a
        # huge value means the Cape-route vessels also sit at berth
        # for a long time after their Cape arrival, which is not
        # physically correct but produces the intended visual
        # ("a few idling ships, the rest transiting the Cape"). A
        # future per-vessel override would clean this up.
        port_dwell_minutes=10_000_000,
        start_at=_DEFAULT_START_AT,
        assignments=tuple(
            [
                # Cape-route vessels (Asia -> Durban -> Europe)
                _bind(
                    "901000002",
                    ["SGSIN", "HKHKG", "OMSLL", "ZADUR", "NLRTM"],
                ),  # PACIFIC HORIZON
                _bind(
                    "901000005",
                    ["CNSHA", "SGSIN", "OMSLL", "ZADUR", "NLRTM"],
                ),  # ATLANTIC DAWN
                _bind(
                    "902000001",
                    ["SGSIN", "HKHKG", "INNSA", "ZADUR", "NLRTM"],
                ),  # IRON BULKER
                _bind(
                    "902000002",
                    ["INMUN", "OMSLL", "ZADUR", "NLRTM"],
                ),  # GRAIN VENTURE
                # Idle Mediterranean vessels (2-port loops; the
                # huge global dwell keeps them effectively moored).
                _bind("903000001", ["MTMLA", "GRPIR"]),  # CRUDE VOYAGER
                _bind("901000003", ["ESALG", "ITGOA"]),  # EASTERN PROMISE
            ]
        ),
    )


def _build_storm_rerouting() -> Scenario:
    """North Atlantic storm forcing traffic south via Morocco."""
    return Scenario(
        name="storm_rerouting",
        description=(
            "A North Atlantic storm forces transatlantic traffic south "
            "via Tangier-Med (Morocco). Vessels take a longer southern "
            "route instead of the great-circle."
        ),
        tags=("north_atlantic", "disruption", "storm", "diversion"),
        port_dwell_minutes=240,
        start_at=_DEFAULT_START_AT,
        assignments=tuple(
            [
                _bind("901000005", ["USNYC", "MAPTM", "NLRTM"]),  # ATLANTIC DAWN
                _bind("901000004", ["USNYC", "MAPTM", "ESALG"]),  # CARGO PIONEER
                _bind("903000001", ["NGLOS", "MAPTM", "USNYC"]),  # CRUDE VOYAGER
                _bind("904000003", ["USNYC", "MAPTM", "NLRTM"]),  # DRIVE TRADER
                _bind("902000004", ["USNYC", "MAPTM", "ESALG"]),  # ORE MASTER
            ]
        ),
    )


def _build_quiet_harbor() -> Scenario:
    """Just 2 vessels on a short 2-port loop. Smoke-test the pipeline."""
    return Scenario(
        name="quiet_harbor",
        description=(
            "Just 2 vessels shuttling between Rotterdam and Hamburg. "
            "Useful for smoke-testing the simulator pipeline without "
            "flooding the backend."
        ),
        tags=("smoke", "minimal", "europe"),
        port_dwell_minutes=120,
        start_at=_DEFAULT_START_AT,
        assignments=tuple(
            [
                _bind("904000001", ["NLRTM", "DEHAM"]),  # GENERAL TRADER
                _bind("904000002", ["NLRTM", "DEHAM"]),  # REEF STAR
            ]
        ),
    )


# --- public registry --------------------------------------------------


SCENARIOS: dict[str, Scenario] = _dedup_scenarios(
    [
        _build_default_med(),
        _build_suez_blockage(),
        _build_storm_rerouting(),
        _build_quiet_harbor(),
    ]
)


def get_scenario(name: str) -> Scenario:
    """Look up a scenario by name (case-insensitive).

    Raises ``KeyError`` with a message listing the available scenarios
    if the name is unknown.
    """
    if name in SCENARIOS:
        return SCENARIOS[name]
    # Case-insensitive fallback. Scenario names are always lowercase,
    # so a caller passing an upper-cased env-var value should still
    # resolve.
    lower = name.lower()
    if lower in SCENARIOS:
        return SCENARIOS[lower]
    raise KeyError(
        f"Unknown scenario: {name!r}. "
        f"Available: {', '.join(sorted(SCENARIOS))}"
    )


def list_scenarios() -> list[str]:
    """Return all registered scenario names, sorted alphabetically."""
    return sorted(SCENARIOS)


__all__ = [
    "Scenario",
    "SCENARIOS",
    "get_scenario",
    "list_scenarios",
]


# --- import-time sanity checks --------------------------------------
# These run when the module is first imported. They catch typos in
# MMSI/UN/LOCODE strings in the builders above (which would otherwise
# only surface when the user actually picks that scenario).

# Sanity: every port used by every scenario must exist in PORTS.
# (This is enforced at build time by ``_bind`` calling ``get_port``,
# but we double-check by walking the registry here.)
_used_ports: set[str] = set()
for _s in SCENARIOS.values():
    for _v, _ps in _s.assignments:
        for _p in _ps:
            _used_ports.add(_p.un_locode)
_unknown = _used_ports - {p.un_locode for p in PORTS}
if _unknown:
    raise RuntimeError(
        f"Scenarios reference unknown ports: {sorted(_unknown)}"
    )

# Sanity: every vessel used must exist in VESSELS. (Same enforcement
# as above via ``_bind``, but re-asserted for defense in depth.)
_used_vessels: set[str] = set()
for _s in SCENARIOS.values():
    for _v, _ps in _s.assignments:
        _used_vessels.add(_v.mmsi)
_unknown = _used_vessels - {v.mmsi for v in VESSELS}
if _unknown:
    raise RuntimeError(
        f"Scenarios reference unknown vessels: {sorted(_unknown)}"
    )

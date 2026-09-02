"""
Shared dataclasses used across the simulator.

Kept deliberately small and free of framework imports so the simulator
can be unit-tested without FastAPI / SQLAlchemy / Pydantic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class VesselType(str, Enum):
    """AIS vessel type codes (subset — most common merchant categories)."""

    CONTAINER_SHIP = "container_ship"
    BULK_CARRIER = "bulk_carrier"
    TANKER = "tanker"
    GENERAL_CARGO = "general_cargo"
    REEFER = "reefer"
    LNG_CARRIER = "lng_carrier"
    RORO = "roro"


class NavStatus(str, Enum):
    """Subset of AIS navigation status codes (ITU-R M.1371)."""

    UNDER_WAY_ENGINE = "under_way_engine"
    UNDER_WAY_SAILING = "under_way_sailing"
    AT_ANCHOR = "at_anchor"
    MOORED = "moored"
    IN_PORT = "in_port"
    NOT_UNDER_COMMAND = "not_under_command"


@dataclass(frozen=True)
class Port:
    """A maritime port (UN/LOCODE + coordinates + country)."""

    un_locode: str  # e.g. "SGSIN"
    name: str
    country_iso2: str  # e.g. "SG"
    country_name: str
    region: str  # free-form, e.g. "asia", "europe"
    lat: float
    lon: float

    def __post_init__(self) -> None:
        if not (5 <= len(self.un_locode) == 5):
            raise ValueError(f"Invalid UN/LOCODE: {self.un_locode!r}")
        if not (-90.0 <= self.lat <= 90.0):
            raise ValueError(f"Invalid latitude: {self.lat}")
        if not (-180.0 <= self.lon <= 180.0):
            raise ValueError(f"Invalid longitude: {self.lon}")


@dataclass(frozen=True)
class Vessel:
    """Static vessel identity. Mirrors a real AIS message 5 (Ship Static)."""

    mmsi: str  # 9 digits
    imo: str  # 7 digits
    name: str
    vessel_type: VesselType
    flag_iso2: str  # country code (e.g. "HK")
    length_m: float
    beam_m: float
    draught_m: float
    max_speed_knots: float  # service speed

    def __post_init__(self) -> None:
        if not (len(self.mmsi) == 9 and self.mmsi.isdigit()):
            raise ValueError(f"Invalid MMSI (must be 9 digits): {self.mmsi!r}")
        if not (len(self.imo) == 7 and self.imo.isdigit()):
            raise ValueError(f"Invalid IMO (must be 7 digits): {self.imo!r}")
        if not (0 < self.max_speed_knots <= 40):
            raise ValueError(f"Unrealistic max speed: {self.max_speed_knots}")


@dataclass
class Waypoint:
    """A point along a planned route."""

    lat: float
    lon: float
    eta: datetime | None = None  # expected arrival at this waypoint


@dataclass
class Route:
    """A planned route: origin port → waypoints → destination port."""

    origin: Port
    destination: Port
    waypoints: list[Waypoint] = field(default_factory=list)
    total_distance_nm: float = 0.0  # nautical miles
    planned_duration_hours: float = 0.0

    @property
    def destination_un_locode(self) -> str:
        return self.destination.un_locode


@dataclass
class VesselState:
    """Mutable per-tick state for a single vessel."""

    vessel: Vessel
    route: Route
    current_lat: float
    current_lon: float
    current_speed_knots: float  # speed over ground (SOG)
    current_heading_deg: float  # course over ground (COG), 0..360
    current_nav_status: NavStatus = NavStatus.UNDER_WAY_ENGINE
    last_position_update: datetime | None = None
    waypoint_index: int = 0  # which waypoint we're heading toward
    next_waypoint: Waypoint | None = None
    eta_destination: datetime | None = None
    is_in_port: bool = False
    minutes_in_port: float = 0.0  # remaining dwell, float so sub-minute ticks work


@dataclass
class PositionReport:
    """An AIS position report (Message 1/2/3) — the most common emission."""

    event_type: str  # always "position_report"
    ts: datetime
    mmsi: str
    imo: str
    vessel_name: str
    vessel_type: str
    lat: float
    lon: float
    sog: float  # speed over ground, knots
    cog: float  # course over ground, degrees
    heading: float  # true heading, degrees
    nav_status: str
    destination_port_id: str  # UN/LOCODE of next port of call
    eta: datetime | None  # ETA at destination_port_id
    draught: float
    flag: str
    length: float
    beam: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "ts": self.ts.isoformat(),
            "mmsi": self.mmsi,
            "imo": self.imo,
            "vessel_name": self.vessel_name,
            "vessel_type": self.vessel_type,
            "lat": round(self.lat, 5),
            "lon": round(self.lon, 5),
            "sog": round(self.sog, 1),
            "cog": round(self.cog, 1),
            "heading": round(self.heading, 1),
            "nav_status": self.nav_status,
            "destination_port_id": self.destination_port_id,
            "eta": self.eta.isoformat() if self.eta else None,
            "draught": round(self.draught, 1),
            "flag": self.flag,
            "length": self.length,
            "beam": self.beam,
        }


@dataclass
class SimEvent:
    """A non-position event emitted by the simulator (eta_change, port_arrival, …)."""

    event_type: str
    ts: datetime
    mmsi: str
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "ts": self.ts.isoformat(),
            "mmsi": self.mmsi,
            **self.payload,
        }

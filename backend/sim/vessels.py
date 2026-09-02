"""
Fictional vessel definitions used by the simulator.

We deliberately avoid real vessel names, MMSIs, or IMOs to prevent any
confusion with real-world traffic. All identifiers in this file are
synthetic.

MMSI conventions
~~~~~~~~~~~~~~~~

Real MMSIs are 9 digits:

* MID ``200``–``775`` — country codes (e.g. ``477`` = Hong Kong, ``538`` = Marshall Islands).
* For ship stations, the first three digits are the MID.

We use a synthetic MID range (``900``–``999``) that is **not assigned**
by the ITU, so any value emitted from this simulator is obviously
synthetic. (The ``__post_init__`` validator only checks 9 digits — it
does not check MID validity, by design.)

IMO conventions
~~~~~~~~~~~~~~~

Real IMOs are 7 digits and follow the Lloyd's Register check-digit
scheme. We do **not** compute a valid check digit (intentionally — so
real-data sniffers can immediately tell these are synthetic).
"""
from __future__ import annotations

from .types import Vessel, VesselType

# Each tuple: (mmsi, imo, name, vessel_type, flag, length, beam, draught, max_speed)
# All MMSIs use MID 9xx (unassigned) so they're obviously synthetic.
VESSELS: list[Vessel] = [
    # --- Container ships (Asia ↔ Europe / Trans-Pacific) ---
    Vessel(
        mmsi="901000001", imo="9900001", name="MV NORTHERN STAR",
        vessel_type=VesselType.CONTAINER_SHIP, flag_iso2="HK",
        length_m=300.0, beam_m=48.0, draught_m=14.5, max_speed_knots=22.0,
    ),
    Vessel(
        mmsi="901000002", imo="9900002", name="MV PACIFIC HORIZON",
        vessel_type=VesselType.CONTAINER_SHIP, flag_iso2="SG",
        length_m=335.0, beam_m=54.0, draught_m=15.0, max_speed_knots=23.0,
    ),
    Vessel(
        mmsi="901000003", imo="9900003", name="MV EASTERN PROMISE",
        vessel_type=VesselType.CONTAINER_SHIP, flag_iso2="MH",
        length_m=290.0, beam_m=45.0, draught_m=14.0, max_speed_knots=21.0,
    ),
    Vessel(
        mmsi="901000004", imo="9900004", name="MV CARGO PIONEER",
        vessel_type=VesselType.CONTAINER_SHIP, flag_iso2="LR",
        length_m=260.0, beam_m=42.0, draught_m=13.5, max_speed_knots=20.0,
    ),
    # --- Bulk carriers ---
    Vessel(
        mmsi="902000001", imo="9901001", name="MV IRON BULKER",
        vessel_type=VesselType.BULK_CARRIER, flag_iso2="GR",
        length_m=225.0, beam_m=32.0, draught_m=14.0, max_speed_knots=15.0,
    ),
    Vessel(
        mmsi="902000002", imo="9901002", name="MV GRAIN VENTURE",
        vessel_type=VesselType.BULK_CARRIER, flag_iso2="PA",
        length_m=190.0, beam_m=30.0, draught_m=11.0, max_speed_knots=14.0,
    ),
    Vessel(
        mmsi="902000003", imo="9901003", name="MV COAL CARRIER",
        vessel_type=VesselType.BULK_CARRIER, flag_iso2="MT",
        length_m=200.0, beam_m=32.0, draught_m=12.5, max_speed_knots=14.5,
    ),
    # --- Tankers ---
    Vessel(
        mmsi="903000001", imo="9902001", name="MT CRUDE VOYAGER",
        vessel_type=VesselType.TANKER, flag_iso2="MH",
        length_m=330.0, beam_m=58.0, draught_m=20.0, max_speed_knots=15.5,
    ),
    Vessel(
        mmsi="903000002", imo="9902002", name="MT PRODUCT EXPRESS",
        vessel_type=VesselType.TANKER, flag_iso2="LR",
        length_m=185.0, beam_m=32.0, draught_m=11.5, max_speed_knots=14.5,
    ),
    Vessel(
        mmsi="903000003", imo="9902003", name="MT LNG AURORA",
        vessel_type=VesselType.LNG_CARRIER, flag_iso2="BS",
        length_m=290.0, beam_m=46.0, draught_m=12.0, max_speed_knots=19.5,
    ),
    # --- General cargo / reefer / roro ---
    Vessel(
        mmsi="904000001", imo="9903001", name="MV GENERAL TRADER",
        vessel_type=VesselType.GENERAL_CARGO, flag_iso2="CY",
        length_m=140.0, beam_m=22.0, draught_m=8.5, max_speed_knots=16.0,
    ),
    Vessel(
        mmsi="904000002", imo="9903002", name="MV REEF STAR",
        vessel_type=VesselType.REEFER, flag_iso2="PA",
        length_m=155.0, beam_m=24.0, draught_m=9.0, max_speed_knots=18.0,
    ),
    Vessel(
        mmsi="904000003", imo="9903003", name="MV DRIVE TRADER",
        vessel_type=VesselType.RORO, flag_iso2="NO",
        length_m=200.0, beam_m=32.0, draught_m=10.5, max_speed_knots=19.0,
    ),
    # --- A second wave for traffic density ---
    Vessel(
        mmsi="901000005", imo="9900005", name="MV ATLANTIC DAWN",
        vessel_type=VesselType.CONTAINER_SHIP, flag_iso2="LR",
        length_m=275.0, beam_m=44.0, draught_m=14.0, max_speed_knots=21.0,
    ),
    Vessel(
        mmsi="902000004", imo="9901004", name="MV ORE MASTER",
        vessel_type=VesselType.BULK_CARRIER, flag_iso2="HK",
        length_m=210.0, beam_m=32.0, draught_m=13.0, max_speed_knots=15.0,
    ),
]


def get_vessel(mmsi: str) -> Vessel:
    """Look up a vessel by MMSI. Raises ``KeyError`` if unknown."""
    for v in VESSELS:
        if v.mmsi == mmsi:
            return v
    raise KeyError(f"Unknown vessel MMSI: {mmsi!r}")


__all__ = ["VESSELS", "get_vessel"]

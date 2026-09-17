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
    # The simulator is wired to the *seed* vessel fleet. MMSI / IMO /
    # name / specs here must match the rows in ``scripts/seed.py``
    # exactly — the ETA snapshot service joins AIS reports to seed
    # vessels on MMSI, and the marketplace UI reads ``vessel.name``
    # and ``vessel.vessel_type`` from the seed table. A mismatch
    # (older versions of this file used a parallel "MV NORTHERN STAR"
    # fleet with ``901xxxxxx`` MMSIs) silently broke ETA snapshots:
    # the AIS feed would have live data, the seed vessel would have
    # an MMSI, but the join key never matched and the marketplace
    # UI showed the "no AIS ETA snapshot" warning.
    Vessel(
        mmsi="900000001", imo="9464567", name="MV Marmara",
        vessel_type=VesselType.CONTAINER_SHIP, flag_iso2="TR",
        length_m=350.0, beam_m=48.0, draught_m=15.5, max_speed_knots=22.0,
    ),
    Vessel(
        mmsi="900000002", imo="9789123", name="MV Aegean",
        vessel_type=VesselType.BULK_CARRIER, flag_iso2="GR",
        length_m=290.0, beam_m=45.0, draught_m=18.0, max_speed_knots=20.0,
    ),
    Vessel(
        mmsi="900000003", imo="9598231", name="MV Bosphorus",
        vessel_type=VesselType.TANKER, flag_iso2="PA",
        length_m=330.0, beam_m=60.0, draught_m=20.5, max_speed_knots=24.0,
    ),
    Vessel(
        mmsi="900000004", imo="9843210", name="MV Antalya",
        vessel_type=VesselType.CONTAINER_SHIP, flag_iso2="TR",
        length_m=300.0, beam_m=42.0, draught_m=14.0, max_speed_knots=21.0,
    ),
    Vessel(
        mmsi="900000005", imo="9711234", name="MV Pacific Voyager",
        vessel_type=VesselType.CONTAINER_SHIP, flag_iso2="LR",
        length_m=360.0, beam_m=51.0, draught_m=16.0, max_speed_knots=23.0,
    ),
    Vessel(
        mmsi="900000006", imo="9634567", name="MV North Star",
        vessel_type=VesselType.BULK_CARRIER, flag_iso2="MH",
        length_m=280.0, beam_m=43.0, draught_m=17.5, max_speed_knots=19.0,
    ),
    Vessel(
        mmsi="900000007", imo="9754321", name="MV Istanbul",
        vessel_type=VesselType.GENERAL_CARGO, flag_iso2="TR",
        length_m=150.0, beam_m=23.0, draught_m=9.5, max_speed_knots=18.0,
    ),
    Vessel(
        mmsi="900000008", imo="9823456", name="MV Rotterdam Express",
        vessel_type=VesselType.CONTAINER_SHIP, flag_iso2="NL",
        length_m=340.0, beam_m=47.0, draught_m=15.0, max_speed_knots=22.0,
    ),
    Vessel(
        mmsi="900000009", imo="9987654", name="MV Singapore Pearl",
        vessel_type=VesselType.CONTAINER_SHIP, flag_iso2="SG",
        length_m=320.0, beam_m=46.0, draught_m=14.5, max_speed_knots=21.0,
    ),
    Vessel(
        mmsi="900000010", imo="9645123", name="MV Dubai Star",
        vessel_type=VesselType.LNG_CARRIER, flag_iso2="AE",
        length_m=290.0, beam_m=47.0, draught_m=12.0, max_speed_knots=26.0,
    ),
    Vessel(
        mmsi="900000011", imo="9543210", name="MV Hamburg",
        vessel_type=VesselType.CONTAINER_SHIP, flag_iso2="DE",
        length_m=335.0, beam_m=48.0, draught_m=15.2, max_speed_knots=22.0,
    ),
    Vessel(
        mmsi="900000012", imo="9734567", name="MV Yokohama",
        vessel_type=VesselType.REEFER, flag_iso2="JP",
        length_m=180.0, beam_m=28.0, draught_m=9.0, max_speed_knots=20.0,
    ),
]


_VESSEL_BY_MMSI: dict[str, Vessel] = {v.mmsi: v for v in VESSELS}


def get_vessel(mmsi: str) -> Vessel:
    """Look up a vessel by MMSI. Raises ``KeyError`` if unknown."""
    vessel = _VESSEL_BY_MMSI.get(mmsi)
    if vessel is None:
        raise KeyError(f"Unknown vessel MMSI: {mmsi!r}")
    return vessel


__all__ = ["VESSELS", "get_vessel"]

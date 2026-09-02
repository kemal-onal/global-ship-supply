"""
AVS Global — AIS Data Simulator.

A standalone Python package that generates synthetic AIS-shaped vessel
position data and emits it to the AVS Global backend at
``/api/v1/internal/ais/ingest``.

The simulator is intentionally decoupled from the FastAPI app: it has no
dependency on SQLAlchemy, Pydantic, or any backend module. It can be
developed, unit-tested, and run independently.

Entry point::

    python -m sim.runner --scenario default_med --seed 42

Submodules:

* ``geo`` — Haversine, bearing, great-circle interpolation (pure math).
* ``ports`` — Hand-picked set of ~50 major maritime hubs.
* ``vessels`` — Fictional vessel definitions (MMSI, IMO, name, type, …).
* ``routes`` — Route generation (origin, destination, waypoints).
* ``world`` — Tick loop, ship movement, ETA / port-arrival detection.
* ``events`` — Event schemas (position_report, eta_change, …).
* ``scenarios`` — Built-in scenario definitions.
* ``backend_client`` — HTTP client that POSTs batches to AVS Global.
* ``config`` — Environment-based configuration.
* ``types`` — Shared dataclasses (VesselState, PositionReport, …).
"""

__version__ = "0.1.0"

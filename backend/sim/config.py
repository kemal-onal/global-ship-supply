"""
Configuration for the AIS data simulator.

Loads from environment variables (with sane defaults) and from an
optional ``sim.toml`` / ``sim.yaml`` if pydantic-settings can find one.

We deliberately use **plain Pydantic v2 BaseSettings** rather than the
AVS Global ``Settings`` class — the simulator must remain runnable in
isolation, with no DB / no Redis / no JWT keys.
"""
from __future__ import annotations

import os
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class SimSettings(BaseSettings):
    """Runtime configuration. All values can be overridden by env vars."""

    model_config = SettingsConfigDict(
        env_prefix="SIM_",
        env_file=os.environ.get("SIM_ENV_FILE", ".env.sim"),
        env_ignore_empty=True,
        extra="ignore",
        case_sensitive=False,
    )

    # --- Backend integration ---
    backend_url: str = Field(
        default="http://localhost:8000",
        description="AVS Global backend base URL (no trailing slash).",
    )
    ingest_path: str = Field(
        default="/api/v1/internal/ais/ingest",
        description="Path on the backend that accepts batched position reports.",
    )
    request_timeout_seconds: float = 5.0
    max_batch_size: int = Field(
        default=50,
        description="Maximum number of position reports per HTTP POST.",
    )
    flush_interval_seconds: float = Field(
        default=2.0,
        description="How often to flush accumulated events to the backend (wall clock).",
    )

    # --- Tick loop ---
    tick_seconds: float = Field(
        default=1.0,
        description="Wall-clock seconds between simulator ticks. With sim_time_scale=1.0 this is also 1 sim-second.",
    )
    sim_time_scale: float = Field(
        default=1.0,
        description="Multiplies tick_seconds. 1.0 = real-time, 60.0 = 1 sim minute per wall-clock second.",
    )

    # --- Scenario ---
    scenario: str = Field(
        default="default_med",
        description="Scenario name. See sim.scenarios for available presets.",
    )
    seed: int = Field(
        default=42,
        description="RNG seed. Same seed + scenario = same traffic.",
    )

    # --- Logging ---
    log_level: str = "INFO"
    log_json: bool = False  # human-readable by default; flip to True for structured logs


@lru_cache
def get_settings() -> SimSettings:
    return SimSettings()


# A non-cached accessor is also exported for callers that want to
# re-read env (mostly useful in tests).
settings = get_settings()


__all__ = ["SimSettings", "get_settings", "settings"]

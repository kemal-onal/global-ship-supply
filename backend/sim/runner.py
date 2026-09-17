"""
CLI entry point for the AIS data simulator.

Glues together:
  * ``SimSettings``  — env-var-driven configuration
  * ``get_scenario`` — registry of pre-built traffic patterns
  * ``World``        — the tick loop (advances vessels, emits events)
  * ``EventBatch``   — in-memory buffer of events ready to POST
  * ``BackendClient`` — async HTTP client to the AVS Global backend

Usage::

    python -m sim.runner --scenario default_med --seed 42
    python -m sim.runner --list-scenarios
    python -m sim.runner --dry-run --max-iterations 5

Architecture
------------

The module is split into three small functions so each can be unit
tested without standing up the rest:

* ``parse_args(argv)`` — pure argparse wrapper.
* ``build_runtime(args)`` — turns parsed args into a ``Runtime``
  bundle (settings, scenario, world, batch). Reads env via
  ``SimSettings``.
* ``run_loop(...)`` — the async tick loop. Returns a ``Stats``
  dataclass with totals. No env access; takes everything as
  parameters.
* ``main()`` — the orchestrator: logging setup, signal handling,
  calls into the others, returns an exit code.

This split is what makes the tests small. ``test_runner.py`` can
exercise ``parse_args`` without asyncio, ``build_runtime`` without
network, and ``run_loop`` with a fake backend client.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from .backend_client import BackendClient, IngestResult
from .config import SimSettings, settings
from .events import EventBatch
from .scenarios import SCENARIOS, get_scenario
from .world import World, WorldConfig, make_assignment_from_ports


# A tiny Protocol describing what run_loop() needs from its backend
# client. Both the real ``BackendClient`` and the test fake satisfy
# it structurally — no inheritance required.
class _ClientLike(Protocol):
    async def send_batch(self, batch: EventBatch) -> IngestResult: ...
    async def health_check(self) -> bool: ...


# ────────────────────────────────────────────────────────────────────
# CLI parsing
# ────────────────────────────────────────────────────────────────────


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI args. Pure function — no I/O, no env access.

    Defaults come from ``SimSettings`` via the ``build_runtime`` step,
    not from argparse. This keeps the parser simple and avoids
    duplicating defaults between env and CLI.
    """
    parser = argparse.ArgumentParser(
        prog="python -m sim.runner",
        description=(
            "AVS Global AIS data simulator. Generates synthetic vessel "
            "position reports and POSTs them to the backend's ingest "
            "endpoint."
        ),
    )
    parser.add_argument(
        "--scenario",
        type=str,
        default=None,
        help="Scenario name to run. Use --list-scenarios to see options.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="RNG seed. Same seed + scenario = same traffic.",
    )
    parser.add_argument(
        "--backend-url",
        type=str,
        default=None,
        help="Backend base URL (default from SIM_BACKEND_URL env var).",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=0,
        help=(
            "Stop after this many ticks. 0 = run until interrupted. "
            "Useful for smoke tests and CI."
        ),
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default=None,
        help="Logging level (DEBUG, INFO, WARNING, ERROR).",
    )
    parser.add_argument(
        "--log-json",
        action="store_true",
        help="Emit logs as JSON lines instead of human-readable text.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Run the tick loop but never POST to the backend. "
            "Logs each batch's size and a sample of its contents."
        ),
    )
    parser.add_argument(
        "--list-scenarios",
        action="store_true",
        help="Print the names and descriptions of all registered scenarios, then exit.",
    )
    return parser.parse_args(argv)


# ────────────────────────────────────────────────────────────────────
# Runtime construction
# ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Runtime:
    """The fully-built simulator runtime, ready for ``run_loop``."""

    settings: SimSettings
    scenario_name: str
    world: World
    batch: EventBatch
    scenario_summary: str


def build_runtime(args: argparse.Namespace) -> Runtime:
    """Build the runtime from parsed args + env-driven settings.

    Reads ``SimSettings`` (env-var driven) and overrides the
    scenario / seed / backend-url / log fields from CLI args when
    those flags are present.
    """
    # We re-instantiate SimSettings (not the cached ``settings``)
    # so tests can mutate env vars without LRU cache poisoning
    # biting them. The ``settings`` global is used by the actual
    # runner entry point; tests use this constructor directly.
    sim_settings = SimSettings()

    if args.scenario is not None:
        sim_settings = sim_settings.model_copy(update={"scenario": args.scenario})
    if args.seed is not None:
        sim_settings = sim_settings.model_copy(update={"seed": args.seed})
    if args.backend_url is not None:
        sim_settings = sim_settings.model_copy(
            update={"backend_url": args.backend_url}
        )
    if args.log_level is not None:
        sim_settings = sim_settings.model_copy(
            update={"log_level": args.log_level.upper()}
        )
    if args.log_json:
        sim_settings = sim_settings.model_copy(update={"log_json": True})

    # Resolve the scenario (raises KeyError on unknown name).
    scenario = get_scenario(sim_settings.scenario)

    # WorldConfig picks up the scenario's overrides when present,
    # otherwise uses the runner's defaults from SimSettings.
    world_config = WorldConfig(
        tick_seconds=sim_settings.tick_seconds,
        sim_time_scale=sim_settings.sim_time_scale,
        seed=sim_settings.seed,
        port_dwell_minutes=(
            scenario.port_dwell_minutes
            if scenario.port_dwell_minutes is not None
            else 240
        ),
        start_at=(
            scenario.start_at
            if scenario.start_at is not None
            else datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
        ),
    )

    assignments = [
        make_assignment_from_ports(vessel, list(ports))
        for vessel, ports in scenario.assignments
    ]
    world = World(world_config, assignments)

    batch = EventBatch(
        source="sim",
        scenario=scenario.name,
        seed=sim_settings.seed,
        max_size=sim_settings.max_batch_size,
    )

    return Runtime(
        settings=sim_settings,
        scenario_name=scenario.name,
        world=world,
        batch=batch,
        scenario_summary=scenario.summary(),
    )


# ────────────────────────────────────────────────────────────────────
# Tick loop
# ────────────────────────────────────────────────────────────────────


@dataclass
class Stats:
    """Aggregate counts returned by ``run_loop`` for the final log line."""

    ticks: int = 0
    flushes: int = 0
    reports_emitted: int = 0
    events_emitted: int = 0
    accepted: int = 0
    rejected: int = 0


async def run_loop(
    world: World,
    batch: EventBatch,
    client: _ClientLike,
    *,
    tick_seconds: float,
    flush_interval_seconds: float,
    max_iterations: int = 0,
    stop_event: asyncio.Event | None = None,
    dry_run: bool = False,
    log: logging.Logger | None = None,
) -> Stats:
    """Run the tick loop until max_iterations or stop_event is set.

    ``stop_event`` is checked at the top of every iteration. Tests
    can pre-set it to short-circuit the loop; the CLI's signal
    handler sets it on SIGINT/SIGTERM.
    """
    log = log or logging.getLogger("sim.runner")
    stop_event = stop_event or asyncio.Event()

    stats = Stats()
    ticks_since_flush = 0
    next_deadline = time.monotonic()

    while not stop_event.is_set():
        # 1. Drive the world one tick. ``step()`` advances the
        #    simulation clock by ``sim_seconds_per_tick`` and yields
        #    one (report, [events]) tuple per vessel.
        for report, events in world.step():
            batch.add_report(report)
            stats.reports_emitted += 1
            for ev in events:
                batch.add_event(ev)
                stats.events_emitted += 1

        stats.ticks += 1
        ticks_since_flush += 1

        # 2. Flush if the batch is full OR the flush interval has
        #    elapsed. We use the *config's* tick_seconds as the
        #    interval unit (so the interval matches the tick rate
        #    under sim_time_scale).
        interval_elapsed = (
            flush_interval_seconds <= 0
            or ticks_since_flush * tick_seconds >= flush_interval_seconds
        )
        if batch.is_full() or (interval_elapsed and not batch.is_empty()):
            await _flush(batch, client, dry_run, log, stats)
            # Reset the interval baseline: we only count ticks
            # *since the last flush* toward the next interval.
            ticks_since_flush = 0

        # 3. Pace to the next tick. Deadline-based, not
        #    sleep-based, so we don't drift under load.
        next_deadline += tick_seconds
        sleep_for = next_deadline - time.monotonic()
        if sleep_for > 0:
            # Use wait_for on the stop_event so Ctrl+C breaks
            # out of the sleep promptly, not after tick_seconds.
            try:
                await asyncio.wait_for(
                    stop_event.wait(), timeout=sleep_for
                )
                # If wait_for returned without TimeoutError,
                # stop_event is set.
                break
            except asyncio.TimeoutError:
                pass  # normal: deadline reached
        else:
            # Behind schedule — yield to the event loop anyway so
            # we don't peg a CPU.
            await asyncio.sleep(0)

        # 4. Bound the loop in test mode.
        if max_iterations > 0 and stats.ticks >= max_iterations:
            break

    # Final flush of whatever is in the batch.
    if not batch.is_empty():
        await _flush(batch, client, dry_run, log, stats)

    return stats


async def _flush(
    batch: EventBatch,
    client: _ClientLike,
    dry_run: bool,
    log: logging.Logger,
    stats: Stats,
) -> None:
    """Send (or log) the current batch and reset state."""
    if dry_run:
        log.info(
            "DRY-RUN flush: %d item(s) (sample mmsi=%s)",
            len(batch),
            batch.reports[0].get("mmsi", "?") if batch.reports else None,
        )
    else:
        try:
            result = await client.send_batch(batch)
        except Exception as exc:
            # Don't crash the whole run for one bad flush. The
            # next batch will try again; if the backend is down
            # permanently, the user sees a steady stream of
            # errors in the log.
            log.error("flush failed: %s: %s", type(exc).__name__, exc)
            batch.clear()
            return
        log.info(
            "flush: sent=%d accepted=%d rejected=%d",
            len(batch),
            result.accepted,
            result.rejected,
        )
        stats.accepted += result.accepted
        stats.rejected += result.rejected

    stats.flushes += 1
    batch.clear()


# ────────────────────────────────────────────────────────────────────
# Orchestration
# ────────────────────────────────────────────────────────────────────


def _setup_logging(level: str, json_mode: bool) -> None:
    """Configure root logger. Idempotent — safe to call twice."""
    root = logging.getLogger()
    # Clear any existing handlers (e.g. uvicorn's) so the simulator's
    # log format is the only one in the output.
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler(sys.stderr)
    if json_mode:
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S",
            )
        )
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))


class _JsonFormatter(logging.Formatter):
    """Minimal JSON-lines log formatter (no external deps)."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


async def main(argv: list[str] | None = None) -> int:
    """Top-level async entry point. Returns a process exit code."""
    args = parse_args(argv)

    # --list-scenarios is a special case: no settings, no world,
    # no client. Just print and exit.
    if args.list_scenarios:
        print("Available scenarios:")
        for name in sorted(SCENARIOS):
            s = SCENARIOS[name]
            print(f"  {name:20s}  {s.description}")
        return 0

    try:
        runtime = build_runtime(args)
    except KeyError as exc:
        # Scenario name not in registry.
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"error: failed to build runtime: {exc}", file=sys.stderr)
        return 1

    _setup_logging(runtime.settings.log_level, runtime.settings.log_json)
    log = logging.getLogger("sim.runner")

    log.info(
        "starting sim: scenario=%s seed=%d tick=%.2fs scale=%.1fx "
        "vessels=%d flush=%.1fs backend=%s",
        runtime.scenario_name,
        runtime.settings.seed,
        runtime.settings.tick_seconds,
        runtime.settings.sim_time_scale,
        len(runtime.world.states),
        runtime.settings.flush_interval_seconds,
        runtime.settings.backend_url,
    )
    log.info("scenario: %s", runtime.scenario_summary)

    # Signal handling: Ctrl+C (SIGINT) and docker stop (SIGTERM) both
    # trigger a graceful shutdown via the stop_event.
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _on_signal(signame: str) -> None:
        log.info("received %s, shutting down…", signame)
        stop_event.set()

    for signame in ("SIGINT", "SIGTERM"):
        try:
            loop.add_signal_handler(
                getattr(signal, signame), _on_signal, signame
            )
        except NotImplementedError:
            # Windows: signal handlers on the loop aren't available
            # in all configurations. We rely on KeyboardInterrupt
            # bubbling up from ``asyncio.run`` instead. Log a
            # warning once.
            log.debug("signal handler for %s not installed (Windows?)", signame)

    # Open the backend client and run.
    try:
        async with BackendClient(
            base_url=runtime.settings.backend_url,
            ingest_path=runtime.settings.ingest_path,
            timeout_seconds=runtime.settings.request_timeout_seconds,
            max_retries=2,
            retry_backoff_seconds=0.5,
        ) as client:
            # Probe health once at startup so we fail fast if the
            # backend is unreachable. The HTTP client also retries
            # transient failures inside send_batch, so this is a
            # UX nicety, not a hard requirement.
            if not await client.health_check():
                log.warning(
                    "backend health check failed at %s; will retry on each flush",
                    runtime.settings.backend_url,
                )

            stats = await run_loop(
                runtime.world,
                runtime.batch,
                client,
                tick_seconds=runtime.settings.tick_seconds,
                flush_interval_seconds=runtime.settings.flush_interval_seconds,
                max_iterations=args.max_iterations,
                stop_event=stop_event,
                dry_run=args.dry_run,
                log=log,
            )

            log.info(
                "stopped: ticks=%d flushes=%d reports=%d events=%d "
                "accepted=%d rejected=%d",
                stats.ticks,
                stats.flushes,
                stats.reports_emitted,
                stats.events_emitted,
                stats.accepted,
                stats.rejected,
            )
            return 0
    except KeyboardInterrupt:
        log.info("interrupted")
        return 130  # Conventional SIGINT exit code.


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

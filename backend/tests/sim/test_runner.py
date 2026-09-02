"""Tests for ``sim.runner``.

The runner is split into three testable pieces:

* ``parse_args`` — pure argparse, sync.
* ``build_runtime`` — sync, reads env via ``SimSettings``,
  builds the world.
* ``run_loop`` — async, takes everything as parameters.

The tests below cover each in isolation. ``run_loop`` tests use a
fake backend client (a class with the right shape, not a real
``BackendClient``) so the test doesn't need httpx or the network.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import pytest

from sim.backend_client import IngestResult
from sim.events import EventBatch
from sim.runner import (
    Stats,
    build_runtime,
    main,
    parse_args,
    run_loop,
)
from sim.world import World, WorldConfig, make_assignment_from_ports


# --- helpers ---------------------------------------------------------


class _FakeBackend:
    """Stand-in for ``BackendClient`` used by ``run_loop`` tests.

    Records every batch it sees. ``send_batch`` returns whatever
    ``accept`` was last set to; ``health_check`` returns True.
    """

    def __init__(self, accept: int = 1, raise_on_send: bool = False) -> None:
        self.batches: list[EventBatch] = []
        self.send_calls = 0
        self.accept = accept
        self.raise_on_send = raise_on_send

    async def send_batch(self, batch: EventBatch) -> IngestResult:
        self.send_calls += 1
        if self.raise_on_send:
            raise RuntimeError("simulated backend down")
        # Copy the batch (it gets cleared after the call).
        self.batches.append(EventBatch(
            source=batch.source,
            scenario=batch.scenario,
            seed=batch.seed,
            reports=list(batch.reports),
        ))
        return IngestResult(
            accepted=self.accept,
            rejected=len(batch) - self.accept,
            rejected_reasons=[],
        )

    async def health_check(self) -> bool:
        return True


def _runtime_for(
    scenario_name: str = "quiet_harbor",
    *,
    tick_seconds: float = 0.01,
    sim_time_scale: float = 1.0,
    port_dwell_minutes: int = 0,
    max_batch_size: int | None = 50,
    seed: int = 42,
) -> Any:
    """Build a small Runtime for run_loop tests.

    Bypasses ``build_runtime`` so we can tweak ``tick_seconds``
    without the env-driven defaults slowing the test down.
    """
    from sim.scenarios import get_scenario
    from datetime import datetime, timezone

    scenario = get_scenario(scenario_name)
    world = World(
        config=WorldConfig(
            tick_seconds=tick_seconds,
            sim_time_scale=sim_time_scale,
            seed=seed,
            port_dwell_minutes=port_dwell_minutes,
            start_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        ),
        assignments=[
            make_assignment_from_ports(v, list(p))
            for v, p in scenario.assignments
        ],
    )
    batch = EventBatch(
        source="sim",
        scenario=scenario.name,
        seed=seed,
        max_size=max_batch_size,
    )
    return scenario, world, batch


# --- TestParseArgs ---------------------------------------------------


class TestParseArgs:
    def test_defaults(self) -> None:
        ns = parse_args([])
        assert ns.scenario is None
        assert ns.seed is None
        assert ns.backend_url is None
        assert ns.max_iterations == 0
        assert ns.log_level is None
        assert ns.log_json is False
        assert ns.dry_run is False
        assert ns.list_scenarios is False

    def test_scenario_flag(self) -> None:
        ns = parse_args(["--scenario", "quiet_harbor"])
        assert ns.scenario == "quiet_harbor"

    def test_seed_flag(self) -> None:
        ns = parse_args(["--seed", "99"])
        assert ns.seed == 99

    def test_backend_url_flag(self) -> None:
        ns = parse_args(["--backend-url", "http://example:9000"])
        assert ns.backend_url == "http://example:9000"

    def test_max_iterations_flag(self) -> None:
        ns = parse_args(["--max-iterations", "5"])
        assert ns.max_iterations == 5

    def test_dry_run_flag(self) -> None:
        ns = parse_args(["--dry-run"])
        assert ns.dry_run is True

    def test_log_json_flag(self) -> None:
        ns = parse_args(["--log-json"])
        assert ns.log_json is True

    def test_log_level_flag(self) -> None:
        ns = parse_args(["--log-level", "DEBUG"])
        assert ns.log_level == "DEBUG"

    def test_list_scenarios_flag(self) -> None:
        ns = parse_args(["--list-scenarios"])
        assert ns.list_scenarios is True

    def test_unknown_flag_exits(self) -> None:
        with pytest.raises(SystemExit):
            parse_args(["--definitely-not-a-real-flag"])

    def test_scenario_validation_happens_later(self) -> None:
        # parse_args should NOT validate the scenario name — the
        # registry lookup happens in build_runtime. This keeps
        # the parser trivially testable.
        ns = parse_args(["--scenario", "does_not_exist"])
        assert ns.scenario == "does_not_exist"


# --- TestBuildRuntime ------------------------------------------------


class TestBuildRuntime:
    def test_default_scenario(self) -> None:
        ns = parse_args([])
        rt = build_runtime(ns)
        # SimSettings default is "default_med".
        assert rt.scenario_name == "default_med"
        assert len(rt.world.states) == 5  # 5 vessels in default_med
        assert rt.batch.scenario == "default_med"
        assert rt.batch.source == "sim"
        assert rt.batch.max_size == 50

    def test_quiet_harbor(self) -> None:
        ns = parse_args(["--scenario", "quiet_harbor"])
        rt = build_runtime(ns)
        assert rt.scenario_name == "quiet_harbor"
        assert len(rt.world.states) == 2

    def test_unknown_scenario_raises(self) -> None:
        ns = parse_args(["--scenario", "does_not_exist"])
        with pytest.raises(KeyError) as ei:
            build_runtime(ns)
        assert "does_not_exist" in str(ei.value)
        assert "Available:" in str(ei.value)

    def test_cli_seed_overrides_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SIM_SEED", "11")
        ns = parse_args(["--seed", "99"])
        rt = build_runtime(ns)
        assert rt.settings.seed == 99  # CLI wins over env

    def test_env_scenario_when_no_cli(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SIM_SCENARIO", "quiet_harbor")
        ns = parse_args([])  # no --scenario
        rt = build_runtime(ns)
        assert rt.scenario_name == "quiet_harbor"

    def test_cli_backend_url_overrides_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SIM_BACKEND_URL", "http://env-host:8000")
        ns = parse_args(["--backend-url", "http://cli-host:9000"])
        rt = build_runtime(ns)
        assert rt.settings.backend_url == "http://cli-host:9000"

    def test_scenario_port_dwell_overrides_world_default(self) -> None:
        # suez_blockage has port_dwell_minutes=10_000_000. Build
        # its runtime and confirm the WorldConfig picked it up.
        ns = parse_args(["--scenario", "suez_blockage"])
        rt = build_runtime(ns)
        assert rt.world.config.port_dwell_minutes == 10_000_000

    def test_log_level_uppercased(self) -> None:
        ns = parse_args(["--log-level", "debug"])
        rt = build_runtime(ns)
        assert rt.settings.log_level == "DEBUG"


# --- TestRunLoop -----------------------------------------------------


class TestRunLoop:
    async def test_runs_exactly_max_iterations(self) -> None:
        scenario, world, batch = _runtime_for("quiet_harbor", tick_seconds=0.01)
        fake = _FakeBackend(accept=2)
        stop = asyncio.Event()
        stats = await run_loop(
            world, batch, fake,  # type: ignore[arg-type]
            tick_seconds=0.01,
            flush_interval_seconds=10.0,  # never flush on interval
            max_iterations=3,
            stop_event=stop,
            log=logging.getLogger("test"),
        )
        assert stats.ticks == 3
        assert stats.reports_emitted == 6  # 2 vessels * 3 ticks

    async def test_stop_event_short_circuits(self) -> None:
        scenario, world, batch = _runtime_for("quiet_harbor", tick_seconds=0.01)
        fake = _FakeBackend()
        stop = asyncio.Event()
        stop.set()  # already set before the call
        stats = await run_loop(
            world, batch, fake,  # type: ignore[arg-type]
            tick_seconds=0.01,
            flush_interval_seconds=10.0,
            stop_event=stop,
            log=logging.getLogger("test"),
        )
        # Loop exits before doing anything; final flush is empty.
        assert stats.ticks == 0
        assert fake.send_calls == 0

    async def test_flushes_when_batch_full(self) -> None:
        # max_batch_size=2: each tick emits 2 vessels * (1 position
        # report + 1 port_departure event) = 4 items. The
        # ``is_full()`` check runs *after* the tick completes
        # (one tick = one add_report + add_event per vessel). So
        # when the tick ends, the batch has 4 items and we flush
        # all 4.
        scenario, world, batch = _runtime_for(
            "quiet_harbor", tick_seconds=0.01, max_batch_size=2
        )
        fake = _FakeBackend(accept=4)
        stats = await run_loop(
            world, batch, fake,  # type: ignore[arg-type]
            tick_seconds=0.01,
            flush_interval_seconds=10.0,  # interval won't trigger
            max_iterations=3,
            log=logging.getLogger("test"),
        )
        # 3 ticks, all of which produced a full batch (4 items
        # each), plus 0 final-flush items because every batch
        # was already flushed.
        assert stats.flushes == 3
        assert fake.send_calls == 3
        for sent in fake.batches:
            assert len(sent) == 4

    async def test_flushes_on_interval(self) -> None:
        # tick=0.05, flush_interval=0.1. After 2 ticks (0.1s
        # elapsed), the interval triggers a flush. The first tick
        # also fires a port_departure per vessel, so each tick
        # produces 2 position reports + 2 events = 4 items.
        scenario, world, batch = _runtime_for(
            "quiet_harbor", tick_seconds=0.05, max_batch_size=1000
        )
        fake = _FakeBackend(accept=4)
        stats = await run_loop(
            world, batch, fake,  # type: ignore[arg-type]
            tick_seconds=0.05,
            flush_interval_seconds=0.1,
            max_iterations=4,
            log=logging.getLogger("test"),
        )
        # 4 ticks, 2 vessels/tick = 8 reports + 8 events = 16
        # items. With a 0.1s flush interval, the loop flushes
        # after tick 2 (interval hit) and at the final exit
        # flush. So 1 to 3 total flushes depending on timing.
        assert 1 <= stats.flushes <= 3
        assert stats.reports_emitted == 8
        assert stats.events_emitted == 8

    async def test_dry_run_does_not_call_send_batch(self) -> None:
        scenario, world, batch = _runtime_for(
            "quiet_harbor", tick_seconds=0.01, max_batch_size=2
        )
        fake = _FakeBackend()
        stats = await run_loop(
            world, batch, fake,  # type: ignore[arg-type]
            tick_seconds=0.01,
            flush_interval_seconds=10.0,
            max_iterations=3,
            dry_run=True,
            log=logging.getLogger("test"),
        )
        # 3 ticks, 2 vessels each = 6 reports. With max_batch=2
        # the dry-run "flushes" 3 times (counted in stats.flushes)
        # but the backend is never touched.
        assert stats.flushes == 3
        assert fake.send_calls == 0
        assert stats.accepted == 0
        assert stats.rejected == 0

    async def test_failed_flush_does_not_crash_run(self) -> None:
        # If send_batch raises (backend down), the loop logs the
        # error and keeps going.
        scenario, world, batch = _runtime_for(
            "quiet_harbor", tick_seconds=0.01, max_batch_size=2
        )
        fake = _FakeBackend(raise_on_send=True)
        # Silence the expected error log noise.
        log = logging.getLogger("test")
        log.addHandler(logging.NullHandler())
        stats = await run_loop(
            world, batch, fake,  # type: ignore[arg-type]
            tick_seconds=0.01,
            flush_interval_seconds=10.0,
            max_iterations=3,
            log=log,
        )
        assert stats.ticks == 3  # completed all ticks
        assert fake.send_calls == 3  # tried 3 times

    async def test_final_flush_on_exit(self) -> None:
        # If max_iterations stops the loop with a non-empty batch,
        # a final flush should happen.
        scenario, world, batch = _runtime_for(
            "quiet_harbor", tick_seconds=0.01, max_batch_size=1000
        )
        fake = _FakeBackend(accept=4)
        stats = await run_loop(
            world, batch, fake,  # type: ignore[arg-type]
            tick_seconds=0.01,
            flush_interval_seconds=10.0,  # never triggers mid-run
            max_iterations=1,
            log=logging.getLogger("test"),
        )
        # 1 tick, 2 vessels = 2 reports + 2 port_departure events
        # = 4 items. No interval flush, no full-batch flush, but
        # the final flush on exit fires.
        assert stats.flushes == 1
        assert fake.send_calls == 1
        assert len(fake.batches[0]) == 4

    async def test_stats_aggregate_accepted_and_rejected(self) -> None:
        scenario, world, batch = _runtime_for(
            "quiet_harbor", tick_seconds=0.01, max_batch_size=2
        )
        fake = _FakeBackend(accept=1)  # accepts 1, rejects the rest
        stats = await run_loop(
            world, batch, fake,  # type: ignore[arg-type]
            tick_seconds=0.01,
            flush_interval_seconds=10.0,
            max_iterations=3,
            log=logging.getLogger("test"),
        )
        # Each flush has 4 items (2 vessels * 2 each: position +
        # departure). The fake accepts 1 per flush and rejects
        # the remaining 3. So accepted:rejected is 1:3 per flush.
        # We don't pin the exact number of flushes; just verify
        # the per-flush ratio.
        assert stats.accepted > 0
        assert stats.rejected == stats.accepted * 3


# --- TestMain (high-level orchestration) ----------------------------


class TestMain:
    async def test_list_scenarios_prints_and_returns_0(self, capsys) -> None:  # type: ignore[no-untyped-def]
        code = await main(["--list-scenarios"])
        assert code == 0
        out = capsys.readouterr().out
        assert "default_med" in out
        assert "quiet_harbor" in out
        assert "storm_rerouting" in out
        assert "suez_blockage" in out

    async def test_unknown_scenario_returns_1(self, capsys) -> None:  # type: ignore[no-untyped-def]
        code = await main(["--scenario", "does_not_exist"])
        assert code == 1
        err = capsys.readouterr().err
        assert "does_not_exist" in err

    async def test_dry_run_with_max_iterations_returns_0(
        self, capsys
    ) -> None:  # type: ignore[no-untyped-def]
        # No backend running, but dry-run should still succeed.
        code = await main(
            [
                "--scenario", "quiet_harbor",
                "--dry-run",
                "--max-iterations", "2",
            ]
        )
        assert code == 0
        out = capsys.readouterr()
        # Startup + stop logs go to stderr (logging default).
        assert "DRY-RUN flush" in out.err
        assert "stopped:" in out.err

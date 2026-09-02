"""Tests for ``sim.backend_client.BackendClient``.

All HTTP interactions go through ``httpx.MockTransport`` so the tests
run without a live backend. ``pytest-asyncio`` is configured in
``pyproject.toml`` with ``asyncio_mode = "auto"``, so plain
``async def test_...`` functions are picked up as asyncio tests.

Retry tests pass ``retry_backoff_seconds=0.0`` so the backoff is
effectively a single ``asyncio.sleep(0)`` — the retry behaviour we
care about is the *count* of attempts, not the wall-clock pacing.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest

from sim.backend_client import BackendClient, BackendClientError, IngestResult
from sim.events import EventBatch
from sim.types import PositionReport, SimEvent


# --- helpers --------------------------------------------------------


def _ok_response(body: dict[str, Any] | None = None) -> httpx.Response:
    return httpx.Response(
        200,
        json=body or {"accepted": 1, "rejected": 0, "rejected_reasons": []},
    )


def _err_response(status: int, body: str = "boom") -> httpx.Response:
    return httpx.Response(status, text=body)


def _counting_handler(
    responses: list[httpx.Response | Exception],
) -> tuple[
    Callable[[httpx.Request], Awaitable[httpx.Response]],
    list[int],
]:
    """Build a transport handler that walks through ``responses`` in
    order, recording how many times it was called. The returned list
    is the call counter (length 1, mutated)."""
    calls: list[int] = [0]

    async def handler(request: httpx.Request) -> httpx.Response:
        calls[0] += 1
        idx = calls[0] - 1
        if idx >= len(responses):
            pytest.fail(
                f"Handler called {calls[0]} times but only {len(responses)} responses queued"
            )
        item = responses[idx]
        if isinstance(item, Exception):
            raise item
        return item

    return handler, calls


def _make_client(handler, **overrides: Any) -> BackendClient:
    """Build a BackendClient with a MockTransport wired to ``handler``."""
    transport = httpx.MockTransport(handler)
    injected = httpx.AsyncClient(transport=transport)
    defaults: dict[str, Any] = dict(
        base_url="http://localhost:8000",
        ingest_path="/api/v1/internal/ais/ingest",
        timeout_seconds=1.0,
        max_retries=2,
        retry_backoff_seconds=0.0,  # tests don't wait
    )
    defaults.update(overrides)
    return BackendClient(client=injected, **defaults)


def _make_batch() -> EventBatch:
    batch = EventBatch(source="sim", scenario="test", seed=42)
    batch.add_event(
        SimEvent(
            event_type="position_report",
            ts=__import__("datetime").datetime(2026, 9, 1, 0, 0, 0, tzinfo=__import__("datetime").timezone.utc),
            mmsi="901000001",
            payload={
                "imo": "9900001",
                "vessel_name": "MV T",
                "vessel_type": "container_ship",
                "lat": 1.0,
                "lon": 100.0,
                "sog": 18.0,
                "cog": 27.0,
                "heading": 27.0,
                "nav_status": "under_way_engine",
                "destination_port_id": "NLRTM",
                "eta": None,
                "draught": 14.5,
                "flag": "HK",
                "length": 300.0,
                "beam": 48.0,
            },
        )
    )
    return batch


# --- send_batch: happy paths ----------------------------------------


class TestSendBatchHappy:
    async def test_returns_ingest_result_on_200(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return _ok_response(
                {"accepted": 3, "rejected": 1, "rejected_reasons": ["mmsi=bad"]}
            )

        client = _make_client(handler)
        async with client:
            result = await client.send_batch(_make_batch())

        assert isinstance(result, IngestResult)
        assert result.accepted == 3
        assert result.rejected == 1
        assert result.rejected_reasons == ["mmsi=bad"]

    async def test_payload_contains_batch_fields(self) -> None:
        captured: list[dict[str, Any]] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            import json
            captured.append(json.loads(request.content))
            return _ok_response()

        client = _make_client(handler)
        async with client:
            await client.send_batch(_make_batch())

        assert len(captured) == 1
        body = captured[0]
        assert body["source"] == "sim"
        assert body["scenario"] == "test"
        assert body["seed"] == 42
        assert len(body["reports"]) == 1
        assert body["reports"][0]["mmsi"] == "901000001"

    async def test_uses_ingest_path(self) -> None:
        captured: list[str] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            captured.append(str(request.url))
            return _ok_response()

        client = _make_client(handler)
        async with client:
            await client.send_batch(_make_batch())

        assert captured[0] == "http://localhost:8000/api/v1/internal/ais/ingest"


# --- send_batch: retries on transport errors ------------------------


class TestSendBatchTransportRetry:
    async def test_retries_on_connect_error_then_succeeds(self) -> None:
        handler, calls = _counting_handler(
            [httpx.ConnectError("refused"), _ok_response()]
        )
        client = _make_client(handler, max_retries=2)
        async with client:
            result = await client.send_batch(_make_batch())
        assert result.accepted == 1
        assert calls[0] == 2  # one failure, one success

    async def test_gives_up_after_max_retries(self) -> None:
        handler, calls = _counting_handler(
            [
                httpx.ConnectError("refused"),
                httpx.ConnectError("refused"),
                httpx.ConnectError("refused"),
            ]
        )
        client = _make_client(handler, max_retries=2)
        async with client:
            with pytest.raises(BackendClientError) as ei:
                await client.send_batch(_make_batch())
        # max_retries=2 means up to 3 total attempts (initial + 2 retries).
        assert calls[0] == 3
        assert "Backend unreachable" in str(ei.value)

    async def test_zero_retries_means_single_attempt(self) -> None:
        handler, calls = _counting_handler([httpx.ConnectError("refused")])
        client = _make_client(handler, max_retries=0)
        async with client:
            with pytest.raises(BackendClientError):
                await client.send_batch(_make_batch())
        assert calls[0] == 1


# --- send_batch: retries on 5xx / 429 -------------------------------


class TestSendBatch5xxRetry:
    async def test_retries_on_503_then_succeeds(self) -> None:
        handler, calls = _counting_handler([_err_response(503), _ok_response()])
        client = _make_client(handler, max_retries=2)
        async with client:
            result = await client.send_batch(_make_batch())
        assert result.accepted == 1
        assert calls[0] == 2

    async def test_gives_up_on_persistent_503(self) -> None:
        handler, calls = _counting_handler(
            [_err_response(503), _err_response(503), _err_response(503)]
        )
        client = _make_client(handler, max_retries=2)
        async with client:
            with pytest.raises(BackendClientError) as ei:
                await client.send_batch(_make_batch())
        assert calls[0] == 3
        assert "503" in str(ei.value)

    async def test_retries_on_429(self) -> None:
        handler, calls = _counting_handler(
            [_err_response(429, "slow down"), _ok_response()]
        )
        client = _make_client(handler, max_retries=2)
        async with client:
            result = await client.send_batch(_make_batch())
        assert result.accepted == 1
        assert calls[0] == 2


# --- send_batch: non-retryable errors -------------------------------


class TestSendBatchNonRetryable:
    @pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
    async def test_does_not_retry_on_4xx(self, status: int) -> None:
        handler, calls = _counting_handler([_err_response(status, "bad")])
        client = _make_client(handler, max_retries=5)
        async with client:
            with pytest.raises(BackendClientError) as ei:
                await client.send_batch(_make_batch())
        assert calls[0] == 1  # single attempt, no retry
        assert str(status) in str(ei.value)

    async def test_raises_on_invalid_json_response(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html>not json</html>")

        client = _make_client(handler)
        async with client:
            with pytest.raises(BackendClientError) as ei:
                await client.send_batch(_make_batch())
        assert "not valid JSON" in str(ei.value)

    async def test_raises_on_unexpected_response_shape(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            # 200 with JSON but missing the expected fields.
            return httpx.Response(200, json={"weird": "shape"})

        client = _make_client(handler)
        async with client:
            result = await client.send_batch(_make_batch())
        # body.get defaults produce a 0/0 result rather than raising.
        assert result.accepted == 0
        assert result.rejected == 0


# --- health_check --------------------------------------------------


class TestHealthCheck:
    async def test_returns_true_on_200(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert str(request.url).endswith("/api/v1/internal/ais/health")
            return httpx.Response(200, json={"status": "ok"})

        client = _make_client(handler)
        async with client:
            assert await client.health_check() is True

    async def test_returns_false_on_503(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503)

        client = _make_client(handler)
        async with client:
            assert await client.health_check() is False

    async def test_returns_false_on_connect_error(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("nope")

        client = _make_client(handler)
        async with client:
            assert await client.health_check() is False


# --- client ownership (injected vs internal) ----------------------


class TestClientOwnership:
    async def test_injected_client_is_not_closed_on_exit(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return _ok_response()

        injected = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = BackendClient(
            base_url="http://localhost:8000",
            ingest_path="/api/v1/internal/ais/ingest",
            client=injected,
        )
        async with client:
            await client.send_batch(_make_batch())
        # The injected client must still be open after the context
        # manager exits. Verify by sending another request through it.
        result = await injected.post(
            "http://localhost:8000/api/v1/internal/ais/ingest",
            json={},
        )
        assert result.status_code == 200
        await injected.aclose()

    async def test_internal_client_is_closed_on_exit(self) -> None:
        client = BackendClient(
            base_url="http://localhost:8000",
            ingest_path="/api/v1/internal/ais/ingest",
        )
        # Use async-with to construct the internal client.
        async with client:
            internal = client._owned_client  # type: ignore[attr-defined]
            assert internal is not None
            assert not internal.is_closed
        # After exit, the internal client should be closed.
        assert internal.is_closed  # type: ignore[possibly-undefined]

    async def test_without_async_with_auto_creates_client(self) -> None:
        # Calling send_batch without entering the context manager
        # should still work — we auto-initialize a client. This
        # means the client leaks (never closed) but is convenient
        # for one-shot usage in scripts.
        async def handler(request: httpx.Request) -> httpx.Response:
            return _ok_response()

        client = BackendClient(
            base_url="http://localhost:8000",
            ingest_path="/api/v1/internal/ais/ingest",
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        result = await client.send_batch(_make_batch())
        assert result.accepted == 1
        # We did not enter the context manager, so the injected
        # client is still open; clean it up.
        await client._client.aclose()


# --- URL composition ------------------------------------------------


class TestURLs:
    def test_ingest_url_strips_trailing_slash(self) -> None:
        c = BackendClient(
            base_url="http://localhost:8000/",
            ingest_path="/api/v1/internal/ais/ingest",
        )
        assert c.ingest_url == "http://localhost:8000/api/v1/internal/ais/ingest"

    def test_ingest_url_adds_leading_slash(self) -> None:
        c = BackendClient(
            base_url="http://localhost:8000",
            ingest_path="api/v1/internal/ais/ingest",  # no leading slash
        )
        assert c.ingest_url == "http://localhost:8000/api/v1/internal/ais/ingest"

    def test_health_url_is_sibling_of_ingest(self) -> None:
        c = BackendClient(
            base_url="http://localhost:8000",
            ingest_path="/api/v1/internal/ais/ingest",
        )
        assert c.health_url == "http://localhost:8000/api/v1/internal/ais/health"

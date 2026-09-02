"""
Async HTTP client that forwards ``EventBatch`` payloads to the AVS
Global backend's ingest endpoint.

This module is the only place in the simulator that talks to the
network. It is intentionally thin: a small wrapper around
``httpx.AsyncClient`` with a retry policy tuned for "the backend is
on localhost, occasional blips should be tolerated, malformed
payloads should fail fast."

Design
------

* **Constructor injection.** The base URL, timeout, retry budget,
  and (optionally) the underlying ``httpx.AsyncClient`` are all
  constructor arguments. The runner builds a client from
  ``SimSettings``; the unit tests build one with a
  ``httpx.MockTransport`` so no real network is involved.

* **Owned vs injected client.** If you pass ``client=...`` you own
  its lifecycle and ``__aexit__`` will *not* close it. If you don't,
  the wrapper creates one and closes it on exit. This lets the
  runner share a single client across many ``send_batch`` calls
  (good for keep-alive) while the tests can use a fresh mock per
  test without worrying about teardown.

* **Retry policy.**
  - 2xx: return parsed result.
  - 400, 401, 403, 404, 422: raise ``BackendClientError`` (the
    payload is bad; retrying won't help).
  - 429, 5xx, and ``httpx.TransportError`` (connect refused, read
    timeout, DNS): retry with exponential backoff up to
    ``max_retries`` times, then raise.
  - JSON parse error in the response: raise ``BackendClientError``
    (the backend returned something we don't understand).

* **Health check.** ``GET`` on the ``ais/health`` endpoint, never
  raises. Returns True/False so the runner can log "backend down"
  without crashing the whole tick loop.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from .events import EventBatch


# 4xx codes that mean "the request itself is broken" and won't be
# fixed by retrying. Everything else (429, 5xx, network) retries.
_NON_RETRYABLE_4XX = {400, 401, 403, 404, 422}


class BackendClientError(RuntimeError):
    """Raised when the backend returns an unrecoverable error."""


@dataclass
class IngestResult:
    """Parsed result of a single POST to the ingest endpoint."""

    accepted: int
    rejected: int
    rejected_reasons: list[str] = field(default_factory=list)


class BackendClient:
    """Async client for the AVS Global ingest endpoint.

    Usage::

        async with BackendClient("http://localhost:8000", "/api/v1/internal/ais/ingest") as client:
            result = await client.send_batch(batch)
            print(f"accepted={result.accepted} rejected={result.rejected}")
    """

    def __init__(
        self,
        base_url: str,
        ingest_path: str,
        *,
        timeout_seconds: float = 5.0,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.5,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        # Strip any trailing slash so f"{base}{path}" doesn't double-slash.
        self.base_url = base_url.rstrip("/")
        self.ingest_path = ingest_path if ingest_path.startswith("/") else f"/{ingest_path}"
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self._injected_client = client
        self._owned_client: httpx.AsyncClient | None = None

    # --- context manager ---------------------------------------------

    async def __aenter__(self) -> "BackendClient":
        if self._injected_client is None and self._owned_client is None:
            # Reasonable defaults for a localhost-targeted client.
            limits = httpx.Limits(
                max_keepalive_connections=10,
                max_connections=5,
            )
            self._owned_client = httpx.AsyncClient(
                timeout=self.timeout_seconds,
                limits=limits,
            )
        return self

    async def __aexit__(self, *exc: Any) -> None:
        # We only close clients we created. An injected client belongs
        # to its owner (typically the test or the runner that built
        # a custom MockTransport).
        if self._owned_client is not None:
            await self._owned_client.aclose()
            self._owned_client = None

    @property
    def _client(self) -> httpx.AsyncClient:
        if self._injected_client is not None:
            return self._injected_client
        if self._owned_client is None:
            # Caller forgot to use `async with`. Auto-initialize so a
            # one-shot usage still works.
            self._owned_client = httpx.AsyncClient(timeout=self.timeout_seconds)
        return self._owned_client

    # --- public API ---------------------------------------------------

    @property
    def ingest_url(self) -> str:
        return f"{self.base_url}{self.ingest_path}"

    @property
    def health_url(self) -> str:
        # The health endpoint lives at <prefix>/health, one level up
        # from the ingest path. We assume the same router prefix; if
        # the path is e.g. /api/v1/internal/ais/ingest, then
        # /api/v1/internal/ais/health is the right neighbour.
        prefix, _sep, _leaf = self.ingest_path.rpartition("/")
        return f"{self.base_url}{prefix}/health"

    async def send_batch(self, batch: EventBatch) -> IngestResult:
        """POST the batch to the ingest endpoint and return the result.

        Raises ``BackendClientError`` on any non-retryable failure.
        Retries with exponential backoff on transport errors, 429,
        and 5xx; raises ``BackendClientError`` once retries are
        exhausted.
        """
        payload = batch.to_payload()
        url = self.ingest_url
        last_exc: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                response = await self._client.post(url, json=payload)
            except httpx.TransportError as exc:
                last_exc = exc
                if attempt < self.max_retries:
                    await self._sleep_backoff(attempt)
                    continue
                raise BackendClientError(
                    f"Backend unreachable after {self.max_retries + 1} attempts: {exc}"
                ) from exc

            status = response.status_code

            if status < 400:
                # 2xx and 3xx (we don't expect 3xx from this endpoint).
                return self._parse_response(response, status)

            if status in _NON_RETRYABLE_4XX:
                raise BackendClientError(
                    f"Backend rejected batch with {status}: {response.text[:500]}"
                )

            # 429 or 5xx — retry.
            last_exc = BackendClientError(
                f"Backend returned {status}: {response.text[:500]}"
            )
            if attempt < self.max_retries:
                await self._sleep_backoff(attempt)
                continue
            raise last_exc

        # Unreachable: the loop always either returns or raises.
        raise BackendClientError(f"send_batch fell through after {self.max_retries + 1} attempts")

    async def health_check(self) -> bool:
        """GET /health on the same router. Never raises."""
        try:
            response = await self._client.get(self.health_url)
        except httpx.TransportError:
            return False
        return 200 <= response.status_code < 300

    # --- internals ----------------------------------------------------

    async def _sleep_backoff(self, attempt: int) -> None:
        delay = self.retry_backoff_seconds * (2 ** attempt)
        await asyncio.sleep(delay)

    @staticmethod
    def _parse_response(response: httpx.Response, status: int) -> IngestResult:
        try:
            body = response.json()
        except Exception as exc:
            raise BackendClientError(
                f"Backend returned {status} but body is not valid JSON: {response.text[:200]}"
            ) from exc
        try:
            return IngestResult(
                accepted=int(body.get("accepted", 0)),
                rejected=int(body.get("rejected", 0)),
                rejected_reasons=list(body.get("rejected_reasons", [])),
            )
        except (TypeError, ValueError) as exc:
            raise BackendClientError(
                f"Backend returned {status} but body has unexpected shape: {body!r}"
            ) from exc


__all__ = ["BackendClient", "BackendClientError", "IngestResult"]

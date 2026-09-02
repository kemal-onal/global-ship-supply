"""Unit tests for the /api/v1/internal/ais/ingest endpoint.

These tests use FastAPI's ``TestClient`` with a mocked database session
so they run without a live Postgres. The session mock implements just
enough of the AsyncSession interface to capture ``db.add()`` calls and
``db.commit()``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.internal import internal_router
from app.models.ais import AisEventType, AisPositionReport, AisSource


class _FakeSession:
    """Minimal async session double for the AIS ingest endpoint."""

    def __init__(self) -> None:
        self.added: list[Any] = []
        self.committed = False

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.committed = True

    async def execute(self, stmt: Any) -> Any:
        # Mimic the SQLAlchemy chain: result.scalars().all()
        rows: list[Any] = []

        class _ScalarsView:
            def all(self) -> list[Any]:
                return rows

        class _Result:
            def scalars(self) -> _ScalarsView:
                return _ScalarsView()

        return _Result()


@pytest.fixture
def app() -> FastAPI:
    """Build a tiny FastAPI app with only the internal router.

    We deliberately do NOT import ``app.main`` — that would trigger the
    production lifespan (which tries to connect to Postgres) and the
    security middleware (which would inspect our test payloads). For
    unit tests of the ingest endpoint we only need the route handlers
    and their declared dependencies.
    """
    a = FastAPI()
    a.include_router(internal_router, prefix="/api/v1/internal")

    # Track every session instance the override returns so tests can
    # inspect what the route actually saw (since the override is
    # re-invoked per request and would otherwise return a fresh
    # _FakeSession on each call).
    sessions: list[_FakeSession] = []

    # Override the *callable* the route depends on, not the Annotated alias.
    # FastAPI's dependency_overrides key is the underlying function (db_session);
    # DBSession is just an Annotated[AsyncSession, Depends(db_session)] alias.
    from app.deps.auth import db_session

    def _override_db() -> _FakeSession:  # type: ignore[return-value]
        s = _FakeSession()
        sessions.append(s)
        return s

    a.dependency_overrides[db_session] = _override_db
    # Stash the list on the app so tests can grab it.
    a.state.fake_sessions = sessions  # type: ignore[attr-defined]
    return a


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


# --- health endpoint ---------------------------------------------------

def test_health(client: TestClient) -> None:
    r = client.get("/api/v1/internal/ais/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "endpoint": "internal/ais/ingest"}


# --- ingest validation -------------------------------------------------

class TestIngestValidation:
    def test_empty_batch(self, client: TestClient) -> None:
        r = client.post(
            "/api/v1/internal/ais/ingest",
            json={"source": "sim", "scenario": "test", "seed": 42, "reports": []},
        )
        assert r.status_code == 200
        body = r.json()
        assert body == {"accepted": 0, "rejected": 0, "rejected_reasons": []}

    def test_valid_position_report(self, client: TestClient) -> None:
        r = client.post(
            "/api/v1/internal/ais/ingest",
            json={
                "source": "sim",
                "scenario": "default_med",
                "seed": 42,
                "reports": [
                    {
                        "event_type": "position_report",
                        "ts": "2026-09-01T00:00:00Z",
                        "mmsi": "901000001",
                        "imo": "9900001",
                        "vessel_name": "MV NORTHERN STAR",
                        "vessel_type": "container_ship",
                        "lat": 1.26,
                        "lon": 103.82,
                        "sog": 18.5,
                        "cog": 27.5,
                        "heading": 28.0,
                        "nav_status": "under_way_engine",
                        "destination_port_id": "NLRTM",
                        "eta": "2026-09-15T08:00:00Z",
                        "draught": 14.5,
                        "flag": "HK",
                        "length": 300.0,
                        "beam": 48.0,
                    }
                ],
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["accepted"] == 1
        assert body["rejected"] == 0

    def test_bad_mmsi_rejected_by_pydantic(self, client: TestClient) -> None:
        # Pydantic should catch this before we hit the endpoint.
        r = client.post(
            "/api/v1/internal/ais/ingest",
            json={
                "source": "sim",
                "reports": [
                    {
                        "event_type": "position_report",
                        "ts": "2026-09-01T00:00:00Z",
                        "mmsi": "12345",  # too short
                    }
                ],
            },
        )
        assert r.status_code == 422

    def test_non_digit_mmsi_rejected_by_validator(self, client: TestClient) -> None:
        r = client.post(
            "/api/v1/internal/ais/ingest",
            json={
                "source": "sim",
                "reports": [
                    {
                        "event_type": "position_report",
                        "ts": "2026-09-01T00:00:00Z",
                        "mmsi": "90100000A",  # has a letter
                    }
                ],
            },
        )
        assert r.status_code == 422

    def test_unknown_event_type_rejected_per_row(
        self, client: TestClient
    ) -> None:
        # A bad event_type in one row should reject that row only.
        r = client.post(
            "/api/v1/internal/ais/ingest",
            json={
                "source": "sim",
                "reports": [
                    {
                        "event_type": "totally_made_up",
                        "ts": "2026-09-01T00:00:00Z",
                        "mmsi": "901000001",
                    },
                    {
                        "event_type": "port_arrival",
                        "ts": "2026-09-01T01:00:00Z",
                        "mmsi": "901000001",
                    },
                ],
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["accepted"] == 1
        assert body["rejected"] == 1
        assert len(body["rejected_reasons"]) == 1
        assert "totally_made_up" in body["rejected_reasons"][0]

    def test_unknown_source_returns_400(self, client: TestClient) -> None:
        r = client.post(
            "/api/v1/internal/ais/ingest",
            json={
                "source": "satellite_magic",
                "reports": [],
            },
        )
        assert r.status_code == 400
        assert "source" in r.json()["detail"].lower()


# --- ingest persistence ------------------------------------------------

class TestIngestPersistence:
    def test_commit_is_called(
        self, client: TestClient, app: FastAPI
    ) -> None:
        client.post(
            "/api/v1/internal/ais/ingest",
            json={
                "source": "sim",
                "reports": [
                    {
                        "event_type": "position_report",
                        "ts": "2026-09-01T00:00:00Z",
                        "mmsi": "901000001",
                        "lat": 1.0,
                        "lon": 100.0,
                    }
                ],
            },
        )
        # The override stashes the session it handed to the route.
        sessions = app.state.fake_sessions  # type: ignore[attr-defined]
        assert len(sessions) == 1
        session = sessions[0]
        assert session.committed is True
        assert len(session.added) == 1
        row = session.added[0]
        assert isinstance(row, AisPositionReport)
        assert row.mmsi == "901000001"
        assert row.event_type == AisEventType.POSITION_REPORT
        assert row.source == AisSource.SIM

    def test_scenario_and_seed_persist(self, app: FastAPI) -> None:
        client = TestClient(app)
        client.post(
            "/api/v1/internal/ais/ingest",
            json={
                "source": "sim",
                "scenario": "suez_blockage",
                "seed": 99,
                "reports": [
                    {
                        "event_type": "weather_delay",
                        "ts": "2026-09-01T00:00:00Z",
                        "mmsi": "901000001",
                        "payload": {"reason": "storm", "delay_hours": 12},
                    }
                ],
            },
        )
        sessions = app.state.fake_sessions  # type: ignore[attr-defined]
        session = sessions[0]
        row = session.added[0]
        assert row.scenario == "suez_blockage"
        assert row.seed == 99
        assert row.payload == {"reason": "storm", "delay_hours": 12}


# --- positions query (smoke test) --------------------------------------

def test_positions_endpoint_returns_empty_list(client: TestClient) -> None:
    r = client.get("/api/v1/internal/ais/positions")
    assert r.status_code == 200
    assert r.json() == []

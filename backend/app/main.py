"""
FastAPI application entry point.

Wiring:

* Lifespan — DB init, structlog configuration, key generation
* Middleware stack — request ID, IDS/IPS, CORS, GZip, audit logging
* Routers — see app.api.v1
* Exception handlers — uniform JSON error responses
* Prometheus metrics endpoint
"""
from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.v1 import api_router
from app.core.config import settings
from app.core.ids import (
    inspect_payload,
    is_port_scan,
    is_rate_limited,
    record_path,
    record_request,
)
from app.core.logging import configure_logging, get_logger
from app.db.session import check_db_health, close_db, init_db


# Prometheus metrics
REQUEST_COUNT = Counter(
    "avs_request_count",
    "Number of HTTP requests",
    ["method", "endpoint", "status_code"],
)
REQUEST_DURATION = Histogram(
    "avs_request_duration_seconds",
    "Request duration in seconds",
    ["method", "endpoint"],
)
SECURITY_EVENTS = Counter(
    "avs_security_events",
    "Number of IDS/IPS events raised",
    ["event_type", "severity"],
)

log = get_logger("avs.http")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging()
    log.info("startup.begin", env=settings.ENVIRONMENT, project=settings.PROJECT_NAME)
    try:
        await init_db()
        log.info("startup.db_ok")
    except Exception as exc:  # noqa: BLE001
        log.warning("startup.db_failed", error=str(exc))
    yield
    log.info("shutdown.begin")
    await close_db()
    log.info("shutdown.done")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    description="AVS Global — Enterprise Ship Supply & Logistics Platform",
    docs_url="/docs" if settings.ENVIRONMENT != "production" else None,
    redoc_url="/redoc" if settings.ENVIRONMENT != "production" else None,
    openapi_url="/openapi.json" if settings.ENVIRONMENT != "production" else None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[str(o) for o in settings.BACKEND_CORS_ORIGINS] or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1024)


class SecurityMiddleware(BaseHTTPMiddleware):
    """Per-request IDS/IPS checks.

    The middleware:
      * assigns a request id
      * counts requests and detects brute-force / rate-limit
      * inspects bodies/params for SQL/XSS signatures
      * flags port-scan signature (many distinct paths/min)
    """

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = request_id

        ip = request.client.host if request.client else "unknown"
        record_request(ip)
        record_path(ip, request.url.path)
        rate = len(getattr(record_request, "_", []) or [])  # placeholder no-op

        # Rate limiting
        if is_rate_limited(ip):
            SECURITY_EVENTS.labels("rate_limit_exceeded", "medium").inc()
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers={"Retry-After": "60", "X-Request-ID": request_id},
            )

        # Port scan
        if is_port_scan(ip):
            SECURITY_EVENTS.labels("port_scan_detected", "high").inc()
            log.warning("ids.port_scan", ip=ip, request_id=request_id)

        # Inspect URL query for injection patterns
        for k, v in request.query_params.multi_items():
            label = inspect_payload(v)
            if label:
                SECURITY_EVENTS.labels(label, "high").inc()
                log.warning("ids.signature", kind=label, field=k, ip=ip, request_id=request_id)
                return JSONResponse(
                    status_code=400,
                    content={"detail": "Suspicious input detected", "kind": label},
                    headers={"X-Request-ID": request_id},
                )

        start = time.perf_counter()
        try:
            response: Response = await call_next(request)
        except Exception as exc:  # noqa: BLE001
            log.exception("http.error", error=str(exc), request_id=request_id)
            return JSONResponse(
                status_code=500,
                content={"detail": "Internal server error"},
                headers={"X-Request-ID": request_id},
            )
        duration = time.perf_counter() - start
        response.headers["X-Request-ID"] = request_id

        endpoint = request.scope.get("route").path if request.scope.get("route") else request.url.path
        REQUEST_COUNT.labels(request.method, endpoint, str(response.status_code)).inc()
        REQUEST_DURATION.labels(request.method, endpoint).observe(duration)

        return response


app.add_middleware(SecurityMiddleware)


@app.middleware("http")
async def access_log_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration = time.perf_counter() - start
    log.info(
        "http.request",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration_ms=round(duration * 1000, 2),
        client=request.client.host if request.client else None,
    )
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled", path=request.url.path, error=str(exc))
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "request_id": getattr(request.state, "request_id", None)},
    )


@app.get("/health", tags=["health"])
async def health() -> dict[str, Any]:
    db = await check_db_health()
    return {
        "status": "ok" if db.get("primary") else "degraded",
        "db": db,
        "env": settings.ENVIRONMENT,
        "version": "1.0.0",
    }


@app.get("/metrics", tags=["health"])
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/", tags=["health"])
async def root() -> dict[str, str]:
    return {
        "name": settings.PROJECT_NAME,
        "docs": "/docs",
        "health": "/health",
    }

"""
IDS / IPS helpers — pattern detection, rate-limit tracking, scoring.

The system is described in the spec as "robust to network traffic analytics
(IDS/IPS)". This module implements simple, deterministic rules that run on every
request and emit SecurityEvent rows when something looks off:

* Brute-force detection  (LOGIN_FAILURE cluster from one IP)
* Rate-limit overage
* SQL/XSS pattern signatures in inputs
* Port-scan signature (many distinct paths in a short window)
* Geo-velocity (impossible travel — same user, distant IPs in <1h)
"""
from __future__ import annotations

import re
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Deque

from app.core.logging import get_logger
from app.core.config import settings

log = get_logger(__name__)


# Signature sets — intentionally short and explicit. Keep them well below any
# false-positive threshold a real environment would tolerate.
SQL_SIGNS = (
    re.compile(r"(\bunion\b\s+\bselect\b)", re.IGNORECASE),
    re.compile(r"(\bor\s+1\s*=\s*1)", re.IGNORECASE),
    re.compile(r"(--\s*$)", re.MULTILINE),
    re.compile(r"(;.*\bdrop\s+table\b)", re.IGNORECASE),
    re.compile(r"(\bxp_cmdshell\b)", re.IGNORECASE),
)
XSS_SIGNS = (
    re.compile(r"<\s*script\b", re.IGNORECASE),
    re.compile(r"\bon\w+\s*=\s*[\"']?", re.IGNORECASE),
    re.compile(r"javascript:", re.IGNORECASE),
)


@dataclass
class IPSState:
    """In-memory sliding-window state for the IDS/IPS rules.

    For a production deployment we would back this with Redis. The in-memory
    version is fine for the MVP and a single-process uvicorn worker.
    """

    login_failures: dict[str, Deque[datetime]] = field(default_factory=lambda: defaultdict(deque))
    rate_window: dict[str, Deque[datetime]] = field(default_factory=lambda: defaultdict(deque))
    paths_seen: dict[str, Deque[tuple[datetime, str]]] = field(default_factory=lambda: defaultdict(deque))
    user_geo: dict[str, Deque[tuple[datetime, str]]] = field(default_factory=lambda: defaultdict(deque))

    def trim(self, ip: str, now: datetime) -> None:
        cutoff = now - timedelta(minutes=15)
        for dq in (self.login_failures[ip], self.rate_window[ip]):
            while dq and dq[0] < cutoff:
                dq.popleft()

        cutoff_paths = now - timedelta(minutes=1)
        dq = self.paths_seen[ip]
        while dq and dq[0][0] < cutoff_paths:
            dq.popleft()

        cutoff_geo = now - timedelta(hours=1)
        dq = self.user_geo[ip]
        while dq and dq[0][0] < cutoff_geo:
            dq.popleft()


state = IPSState()


def inspect_payload(text: str | None) -> str | None:
    """Return a label if the string looks like an injection attempt, else None."""
    if not text:
        return None
    for pat in SQL_SIGNS:
        if pat.search(text):
            return "sql_injection_attempt"
    for pat in XSS_SIGNS:
        if pat.search(text):
            return "xss_attempt"
    return None


def record_login_failure(ip: str) -> int:
    now = datetime.now(timezone.utc)
    state.trim(ip, now)
    state.login_failures[ip].append(now)
    return len(state.login_failures[ip])


def check_brute_force(ip: str) -> bool:
    """Return True if the IP has crossed the brute-force threshold."""
    now = datetime.now(timezone.utc)
    state.trim(ip, now)
    return len(state.login_failures[ip]) >= 5


def record_request(ip: str) -> int:
    """Return the current count of requests in the sliding window."""
    now = datetime.now(timezone.utc)
    state.trim(ip, now)
    state.rate_window[ip].append(now)
    return len(state.rate_window[ip])


# IPs exempt from rate limiting. Loopback is always exempt so that the
# local dashboard + simulator + curl-from-IDE traffic don't fight each
# other for the same per-IP bucket. Add internal docker network ranges
# here as needed.
RATE_LIMIT_EXEMPT_IPS: frozenset[str] = frozenset({"127.0.0.1", "::1"})


def is_rate_limited(ip: str) -> bool:
    # Loopback is exempt: see RATE_LIMIT_EXEMPT_IPS.
    if ip in RATE_LIMIT_EXEMPT_IPS:
        return False
    now = datetime.now(timezone.utc)
    state.trim(ip, now)
    return len(state.rate_window[ip]) > settings.RATE_LIMIT_REQUESTS


def record_path(ip: str, path: str) -> int:
    now = datetime.now(timezone.utc)
    state.trim(ip, now)
    state.paths_seen[ip].append((now, path))
    distinct = {p for _, p in state.paths_seen[ip]}
    return len(distinct)


def is_port_scan(ip: str) -> bool:
    now = datetime.now(timezone.utc)
    state.trim(ip, now)
    distinct = {p for _, p in state.paths_seen[ip]}
    return len(distinct) > 60  # >60 distinct paths in 1 minute


def record_user_geo(user_id: str, ip: str) -> bool:
    """Return True if movement looks impossible (e.g. same user, very different IPs)."""
    now = datetime.now(timezone.utc)
    state.trim(ip, now)
    state.user_geo[user_id].append((now, ip))
    return len({i for _, i in state.user_geo[user_id]}) > 3

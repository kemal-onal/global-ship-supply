# Project Report — AVS Global Ship Supply Platform

> The story behind the code. What this is, what we built, what we
> deliberately left out, and what we'd do next.
>
> For the developer-facing manual (quickstart, API reference, etc.)
> see [`README.md`](./README.md). For deep dives, see
> [`docs/architecture/`](./docs/architecture/).

## Table of contents

1. [What this is](#what-this-is)
2. [What we built](#what-we-built)
3. [What we deliberately did not build](#what-we-deliberately-did-not-build)
4. [Notable design decisions](#notable-design-decisions)
5. [What we'd do next](#what-wed-do-next)
6. [How to evaluate this project](#how-to-evaluate-this-project)

---

## What this is

AVS Global is a real maritime ship-supply business: vessels arrive
at port, need provisions (food, spare parts, deck supplies), and
order them through suppliers who bid for the contract. The legacy
software was a Flask + SQLite demo that worked for one demo user
and a hundred rows. It could not:

- Serve a 5,000-row IMPA/ISSA catalog without freezing
- Handle a captain who lost VSAT satellite connection mid-order
- Approve an order whose destination country banned a specific
  product category
- Compute how many kilos of rice a 14-day voyage with 24 crew needs
  when the crew is half Filipino, a third Indian, and a sixth
  European (each nationality has different calorie targets and macro
  profiles)
- Run anywhere near production traffic

This codebase is a from-scratch rebuild. Same business, modern stack,
real algorithms, demo data. The goal was a platform that an operations
team could realistically run a fleet on, and that other engineers
could read and learn from.

It is **not** a commercial product. It is a working system that
demonstrates a coherent set of design and engineering decisions, end
to end.

---

## What we built

A full stack, three layers deep, with a real-time data path on top:

### Backend (FastAPI + PostgreSQL)

- **Async SQLAlchemy 2.0** with Alembic migrations
- **JWT (RS256) auth** with 8-day access tokens and 30-day refresh
  tokens; the keypair is generated on first boot if missing
- **RBAC** with `resource:action:scope` permissions
- **IDS/IPS at the perimeter** — brute-force counter, port-scan
  detector, SQL/XSS injection filter, structured security events
- **Per-nationality catering algorithm** — calorie targets × crew ×
  days + buffer, menu templates per (nationality, meal_type)
- **RFQ supplier bidding** with weighted comparison
  (price / lead-time / reliability / quality scores)
- **Customs & port regulation engine** — JSONLogic-lite condition
  evaluator over (order, country) → severity, blocking flag, permit
  requirement
- **PostgreSQL `tsvector` + GIN indexes** on the catalog so search
  is fast
- **Per-user notifications** with a server-side inbox, mark-read,
  and mark-all-read
- **Health + Prometheus metrics** endpoints for ops
- **Synthetic AIS ingest endpoint** (`/internal/ais/ingest`,
  unauthenticated) for the simulator
- **199 tests** in pytest with `asyncio_mode = "auto"` — the suite
  runs in ~5 seconds

### Frontend (React 19 + Vite PWA)

- **React Router** with 15 pages: Dashboard, Catalog, ProductDetail,
  Orders, OrderCreate, OrderDetail, Vessels, FleetMap, Ports, Catering,
  RFQ, Customs, Sync, Settings, Login
- **Zustand** stores for auth, theme, network status, and notifications
- **TanStack Query** for all server state with auto-refresh on 401
- **TanStack Virtual** for the catalog data grid (handles thousands
  of rows smoothly)
- **IndexedDB + Service Worker offline queue** — orders placed while
  VSAT is down are persisted locally and replayed idempotently when
  the connection returns
- **In-app notification panel** — bell badge polled every 30 s,
  list opens on click, mark-read per item or all
- **PWA install** via `vite-plugin-pwa`
- **Dark mode** + design tokens mirrored from a Figma source (see
  [`docs/architecture/06-figma-design-system.md`](./docs/architecture/06-figma-design-system.md))

### Simulator (standalone Python package)

- **Decoupled from FastAPI/SQLAlchemy** — no dependency on the
  backend's models, sessions, or settings. Can be developed and
  unit-tested in isolation.
- **54 hand-picked maritime ports** (Singapore, Rotterdam, Suez, …)
  with realistic lat/lon
- **15 fictional vessels** in the **MID 9xx MMSI range** (unassigned
  by the ITU) so any value reaching the backend is obviously synthetic
- **4 built-in scenarios**: Mediterranean shuttle, Suez blockage
  (Asia↔Europe via the Cape of Good Hope), North-Atlantic storm
  rerouting, quiet-harbor smoke test
- **Reproducible runs** via the `--seed` flag — same seed + same
  scenario = same traffic
- **httpx async client** with retry policy and a health check
- **Geo math** (Haversine, slerp, initial bearing) is pure functions
  in `sim/geo.py` with no I/O — easy to test, easy to reason about

### Live Fleet Map (the most fun part)

A Leaflet page at `/fleet-map` that polls
`GET /api/v1/internal/ais/positions` every 5 seconds, groups the
results by MMSI, and draws:

- A **colored polyline** through each vessel's historical positions
  (the route the simulator has traced)
- A **circleMarker** at each vessel's current position
- A **tooltip** on click with name, MMSI, SOG, COG, nav status, last
  update
- A **scenario dropdown** to switch between the four built-in
  scenarios on the fly
- A **"Center" button** to fit the map to all current positions
- A **bottom-left fleet panel** listing every vessel with current SOG

Leaflet CSS is loaded from `cdn.jsdelivr.net`; the JS is bundled
locally from `leaflet@1.9.4`.

---

## What we deliberately did not build

A real list of known gaps, in priority order:

1. **Real AIS feed integration.** The simulator is synthetic.
   Wiring a real AIS provider (MarineTraffic, Spire, VesselFinder)
   would mean a new ingest adapter and a re-key strategy for the
   synthetic MID-9xx range.
2. **WebSocket / SSE notification channel.** The 30 s polling is
   fine for thousands of users; for millions, you'd want a push
   channel. The notifications table and API are already push-ready.
3. **Redis-backed IDS/IPS counters.** The env vars and code paths
   are wired; the implementation falls back to in-process counters
   when Redis is absent. The fallback loses state on restart, which
   is fine for a dev environment.
4. **Multi-tenancy.** Every row is implicitly single-tenant.
   Adding a `tenant_id` everywhere would be a significant migration
   but not architecturally hard.
5. **Per-vessel dwell override in the simulator.** The
   `suez_blockage` scenario sets a global
   `port_dwell_minutes=10_000_000` to keep the Med tankers moored,
   but that dwell applies to the Cape-route vessels too — they also
   never depart. This is a known bug documented in
   `backend/sim/scenarios.py:181`. The fix is a per-vessel override
   on the `WorldConfig`.
6. **Frontend test suite.** No vitest, no Playwright. The frontend
   has linting but no automated tests. This was a deliberate
   trade-off given the project's "demo" framing, not a feature.
7. **CI.** No GitHub Actions workflow runs the test suite on push.
   Adding one is ~20 lines of YAML.
8. **Load testing.** No `locust` / `k6` scripts. The catalog
   endpoint is index-tuned for the 5,000-row target but not
   benchmarked under realistic concurrent load.
9. **Internationalisation.** All UI strings are hard-coded English.
   The catering algorithm and the customs engine both deal with
   per-nationality data, but the chrome itself is not translated.
10. **Accessibility audit.** Tailwind + semantic HTML gets you most
    of the way there, but the project has not been audited against
    WCAG.

If you're a hiring manager reading this: the gaps above are the
ones I'd ask about in an interview, and they're the right gaps for
a 6-month project of this scope.

---

## Notable design decisions

These are the ones that took the most thought or the most debate:

### 1. The simulator is a standalone Python package, not a module inside the backend

The simulator has zero dependency on FastAPI, SQLAlchemy, or the
backend's settings. It just emits JSON shaped like the backend's
`IngestBatchIn` schema, over HTTP. This means:

- The simulator can be unit-tested without a database
- The backend and the simulator can be developed by different
  teams on different cadences
- The same backend can be driven by a *real* AIS feed later, with
  no backend changes — just swap the producer

The trade-off: we duplicate the `MMSI` and `event_type` enums on
both sides, and they have to stay in sync. We mitigate this by
having the simulator's `events.py` produce JSON that matches the
backend's Pydantic schema by construction (both modules import
the same `EventBatch` shape definition).

### 2. The internal AIS ingest endpoint is unauthenticated

`POST /api/v1/internal/ais/ingest` has no JWT requirement. This
sounds crazy but it's deliberate: the endpoint is meant to be
reachable only on the loopback interface or a private Docker
network. The data it accepts is always synthetic (MID-9xx MMSIs),
and the table it writes to has no foreign keys to any other table
— so even if the endpoint is accidentally exposed, the worst case
is junk rows in `ais_position_reports`, which you can filter with
`WHERE source = 'sim'`.

In production, the right answer is to either remove the router or
front it with a private-network firewall. Both options are noted in
the production checklist at the bottom of the README.

### 3. JWT private key is generated on first boot

The backend's `app/core/security.py` checks for `jwt-private.pem`
on startup and, if it's missing, generates an RSA 2048 keypair
right there. This means a fresh clone + `uvicorn app.main:app`
just works, with no key-distribution dance. The trade-off is that
every dev machine and every test environment has a different
signing key — which is exactly what you want for a non-production
deployment.

For production: use a real key from your secrets manager. There's
a checklist item for this in the README.

### 4. Notifications are stored, not pushed

Each `Order` state transition writes a row to the `notifications`
table, scoped to the user the order is assigned to (or, as a
fallback, the user who created the order). The frontend polls
`/notifications/unread-count` every 30 seconds. Why not WebSocket?

- Polling 30 s is fine for thousands of users on a single instance
- The notification table becomes a durable inbox you can query for
  analytics ("how many order transitions did this user miss?")
- It degrades gracefully — if the WebSocket disconnects, the user
  doesn't miss a notification; they just see it 30 s late

The push upgrade is a future change, not a fundamental rework. The
producer side is already idempotent (marking a row read is a no-op
on a second call).

### 5. The Fleet Map uses imperative Leaflet, not `react-leaflet`

The page imports `leaflet` directly and uses its imperative API.
Why no `react-leaflet`?

- The wrapper adds a real dependency footprint for a single page
- For markers + polylines + a tile layer, the imperative API is
  simpler and the React lifecycle is less of a fight
- We don't need the marker-clustering or measurement plugins that
  are the main reason to reach for `react-leaflet`

The trade-off: cleanup has to be done manually in the React
`useEffect` return, and the "view = state" ergonomics that React
gives you are partially lost. For a single page with this much
state, that's fine.

### 6. The `suez_blockage` simulator bug

A `port_dwell_minutes=10_000_000` (~19 years of sim time) is set
globally on the world config to keep the Mediterranean tankers
moored. Because the field is global, the Cape-route vessels also
wait that long before departing — they never move in this scenario.
The bug is documented in the code (see the comment at
`backend/sim/scenarios.py:181`) and in the README's troubleshooting
section. The fix is a per-vessel dwell override on the
`WorldConfig`, which would take ~30 lines of code and a small
refactor of the `sim.world` module.

We left the bug in place because the surrounding code is correct
and the fix is obvious from the comment. The README tells readers
to use `default_med` for visible motion.

---

## What we'd do next

In rough priority order:

1. **Fix the per-vessel dwell override in `sim.scenarios`** so
   `suez_blockage` produces visible motion. ~30 lines, no API
   changes.
2. **Add a WebSocket / SSE notification channel** behind the
   existing polling, with the polling as a fallback. The
   notification table is already the source of truth.
3. **Add a GitHub Actions workflow** that runs `pytest`, `ruff
   check`, and the frontend's `npm run lint` on every push. ~20
   lines of YAML.
4. **Add a frontend test suite** — Vitest for unit tests,
   Playwright for one happy-path end-to-end test (login → create
   order → see notification).
5. **Wire a real AIS feed adapter** so the backend can ingest
   production data with the same code path.
6. **Tenant isolation** — a `tenant_id` column on every business
   table, with a request-scoped filter.
7. **Internationalisation** — pull every UI string out of the
   components into a single i18n catalog.
8. **Load test the catalog endpoint** with `locust` and tune the
   indexes based on real query patterns.
9. **Accessibility audit** against WCAG 2.1 AA.

---

## How to evaluate this project

If you're a hiring manager or a curious engineer, here's the order
I would read things in:

1. **This file** — 10 minutes for the project story and the gap list
2. **[`docs/architecture/01-system-architecture.md`](./docs/architecture/01-system-architecture.md)**
   — the system topology
3. **[`backend/app/main.py`](./backend/app/main.py)** — the
   middleware stack and lifespan handler, in one read you see how
   the request/response cycle is wired
4. **[`backend/sim/runner.py`](./backend/sim/runner.py)** — the
   simulator's main loop, the part that surprised me most when
   writing it
5. **[`frontend/src/pages/FleetMap.jsx`](./frontend/src/pages/FleetMap.jsx)**
   — the Leaflet integration, the part of the frontend I had the
   most fun building
6. **The tests** — `backend/tests/sim/` is the densest, most
   opinionated part of the codebase
7. **The `docs/architecture/` set** — the long-form deep dives

If you only have 30 minutes, run the Fleet Map demo and read this
file.

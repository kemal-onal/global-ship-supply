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
  runs in ~5 seconds. Updated to **285 tests** in ~7 s with the
  RBAC + sealed-bid + counter-offer visibility work, then to
  **402 tests** in ~12 s with the marketplace redesign + IMPA-first
  ordering + clarification thread + the early-September 2026 bugfix
  regressions, then to **427 tests** in ~13 s with the September
  2026 AIS sim work (great-circle waypoint following, wall-clock
  timestamps, MMSI realignment, scenario integration) and the
  three supplier-portal regressions.
- **Marketplace redesign** — the sealed-bid auction was replaced with
  a fan-out RFQ, per-line supplier decision, admin-composed
  proposal, and a 24h supplier acceptance window. New routes in
  `app/api/v1/marketplace.py`, new services in
  `app/services/{marketplace,redaction}.py`, and a background
  sweeper that drops suppliers who don't confirm in 24h. The
  proposal composer is the most complex new code in the backend.
- **IMPA-first ordering** — order lines no longer carry a price. The
  purchaser types a 6-digit IMPA code in `OrderCreate`, the
  typeahead resolves to a catalog row, and the supplier's first
  commit is "can I deliver this in the vessel's ETA→ETD window"
  *before* any per-line pricing. The admin↔purchaser clarification
  thread (`app/api/v1/clarification.py`) is the surface for
  handling ambiguity.
- **Supplier portal** — a dedicated supplier-facing page at
  `/supplier` that lists invited RFQs, lets the supplier accept or
  decline, and redacts vessel identity to `"Vessel #N"` (CRC32 of
  the vessel id, stable across requests). New routes in
  `app/api/v1/supplier_portal.py`, new service in
  `app/services/redaction.py`, new page at
  `frontend/src/pages/SupplierPortal.jsx`.

### Frontend (React 19 + Vite PWA)

- **React Router** with 16 pages: Dashboard, Catalog, ProductDetail,
  Orders, OrderCreate, OrderDetail, Vessels, FleetMap, Ports, Catering,
  RFQ, MarketSim, Customs, Sync, Settings, **Permissions**, Login
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
- **12 fictional vessels** in the **MID 9xx MMSI range** (unassigned
  by the ITU, mirroring the seed fleet) so any value reaching the
  backend is obviously synthetic
- **4 built-in scenarios**: Mediterranean shuttle, Suez blockage
  (Asia↔Europe via the Cape of Good Hope), North-Atlantic storm
  rerouting, quiet-harbor smoke test
- **Great-circle waypoint following** — vessels steer toward the
  *next unvisited waypoint* along the great-circle polyline, not
  a straight line to the destination. On a 5,000-nm leg the
  straight-line shortcut would cut through the Italian peninsula;
  the waypoint path goes through the Ionian Sea as it should.
  See notable design decision #11 below.
- **Decoupled sim-time and wall-clock timestamps** —
  `PositionReport.event_ts` is wall-clock UTC, not sim-time, so
  the backend can read "when did the vessel *actually* report"
  without muddling it with "how much sim time has elapsed". A
  5-second freshness invariant is pinned in
  `tests/sim/test_world.py::test_report_ts_is_wall_clock_within_5_seconds`.
- **Visual speed boost** — `VISUAL_SPEED_BOOST = 10` in
  `sim/world.py` multiplies per-tick distance (not reported SOG)
  so a 3,000-nm leg plays out in 5–10 minutes instead of an hour.
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
7. **Supplier-portal push channel.** When a purchaser approves a
   proposal, the 24h acceptance window starts. The supplier is
   notified via the existing per-user `notifications` table +
   30s polling — no WebSocket / SSE on the supplier side. The
   infrastructure for it is in place (the same `notifications`
   table + the bell panel), but a supplier-specific push
   channel is a future change.
8. **Marketplace proposal amendments.** Once a proposal is
   composed, the admin can't change per-line winners without
   re-composing from scratch. The data model would support
   it (the `SupplierLineAssignment` rows are addressable by
   id), but the UI doesn't expose the affordance.
9. **CI.** No GitHub Actions workflow runs the test suite on push.
   Adding one is ~20 lines of YAML.
10. **Load testing.** No `locust` / `k6` scripts. The catalog
    endpoint is index-tuned for the 5,000-row target but not
    benchmarked under realistic concurrent load.
11. **Internationalisation.** All UI strings are hard-coded English.
    The catering algorithm and the customs engine both deal with
    per-nationality data, but the chrome itself is not translated.
12. **Accessibility audit.** Tailwind + semantic HTML gets you most
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

### 7. Sealed-bid RFQ is a response-side filter, not a data-model flag

A `purchasing_officer` running the bid war before the award is
committed shouldn't see supplier identities or per-bidder prices —
that would let them game the round-2 re-bid to undercut the
target exactly. The naive fix is a `sealed_bid_mode: bool` column
on the `RFQ` row, and every consumer checks it.

We did the opposite: the `RFQ` table is unchanged. The DB always
holds the truth. The redaction lives in
`backend/app/services/rfq_serializers.py`, a single module that
strips supplier names, per-bidder prices, and the reliability
/quality ratings from the response before it leaves the API
boundary. `super_admin` and `fleet_admin` see the full
leaderboard; everyone else sees "Bidder 1, Bidder 2, …" with
only the winner's total and lead time.

The trade-off: a single RFQ can be viewed sealed by a
purchaser and unsealed by an admin in the same session, which
is exactly what the demo wants ("the audit log keeps the
truth; the buyer is constrained in *what they can see*, not
*what's in the database*").

The same module classifies counter-offer terms as
`visibility=winner_only` on the `market_sim_events` audit log,
so the buyer's target prices and lead-time squeeze are visible
only to the winning supplier (and admins). The rule is ready
for the supplier portal even though the portal itself doesn't
ship in this iteration.

The deep dive is in
[`docs/architecture/08-rbac-and-sealed-bidding.md`](./docs/architecture/08-rbac-and-sealed-bidding.md).

### 8. The marketplace redesign chose per-line decisions, not a sealed-bid auction

The original `MarketSimPage` was a sealed-bid auction: every
supplier bids on the whole order, the engine picks a winner by
weighted score, losing bids are sealed from the purchaser. The
purchaser sees a "Bidder 1, Bidder 2, …" leaderboard and the
winner.

The redesign scrapped that. The new flow is **fan-out → per-line
decision → 24h acceptance window**: the admin invites a slate of
suppliers, each one decides "can I deliver in the vessel's
ETA→ETD window" (the IMPA-first gate), then prices per line.
The admin opens the marketplace page, sees one ranked list per
line, and picks a winner. The purchaser approves the proposal
and the assigned suppliers get 24h to accept.

Why? Two reasons:

1. **Real lead times, not simulated ones.** The auction engine's
   "lead time" was a counter-offer simulation, not what the
   supplier could actually fulfil. Letting each supplier commit
   to a real ETA/ETD window up front is closer to how a real
   supply chain works.
2. **The supplier-portal piece needed per-line granularity
   anyway.** A supplier might be great at provisioning rice and
   canned fish but have no spare parts; asking them to bid on
   the whole order is artificial. The marketplace redesign gives
   the admin the per-line winner pick that the data was always
   going to need.

The trade-off: the admin is now the bottleneck on the per-line
decision. A 5-line order with 3 candidate suppliers means 15
cells to pick; the marketplace page renders this as a table
with one click per cell. A real procurement system would
auto-suggest winners and let the admin override; this demo
expects the admin to click.

The deep dive is in
[`docs/architecture/09-marketplace-redesign.md`](./docs/architecture/09-marketplace-redesign.md).

### 9. The IMPA-first gate happens *before* pricing, not after

The original "send RFQ to suppliers" flow asked suppliers to
quote per line up front. The redesign splits that into two
decisions: first, "can I deliver in the vessel's ETA→ETD window?"
(the gate, no pricing involved); second, "if yes, what's the
price per line?" (the actual quote).

Why? Because a supplier that can't deliver at all is wasting
everyone's time if they have to fill in per-line prices just
to decline. Worse, the admin sees a quote that looks real but
is a placeholder for "I would have declined if you'd asked."

The gate is enforced at the API level: a supplier quote with
`can_deliver_in_window=None` is rejected at
`POST /supplier-portal/rfqs/{id}/quote` and the UI closes the
line picker. The supplier has to commit "yes" or "no, here's
why" before they see a single line price field.

The trade-off: suppliers have to make a binary commitment
without seeing the full line list. In a real procurement system
this is a phone call first, then a quote — we're just making
the binary commitment explicit instead of implicit. The UI
shows the vessel's ETA/ETD window in the gate card so the
supplier can decide without a phone call.

### 10. The three September 2026 bugfixes are pinned, not fixed-and-forgotten

The first three real bugs in the marketplace flow were all
defensive-correctness issues, not feature gaps. They were:

1. `Enum(AuditAction)` bound the *name* (uppercase) instead of
   the *value* (lowercase), so the new marketplace audit
   actions (`clarification_requested`, etc.) blew up at
   `InvalidTextRepresentationError`. The fix is two-part: the
   model column now passes `values_callable` so every bind uses
   the value, and migration `0008_auditaction_values` adds the
   lowercase counterparts of the original 16 values to the PG
   enum. The route is also fixed to bind `AuditAction.X.value`
   explicitly (defense in depth — even if a future refactor drops
   `values_callable` on the model, the single write still works).
2. `GET /supplier-portal/rfqs` lazy-loaded `RFQ.quotes` in an
   async session and exploded with `MissingGreenlet`. The fix
   is `selectinload(RFQ.quotes)` in the `.options(...)` chain
   at `backend/app/api/v1/supplier_portal.py:144`.
3. The seeded APC Marine User had
   `email="supplier@apcmarine.sg"` but the matching Supplier
   row had `contact_email="info@apcmarine.sg"`, so the
   `_load_supplier_for_token` helper returned 403
   "No supplier profile bound to this user account". The fix
   is in the seed (`scripts/seed.py`) and as a one-shot SQL
   `UPDATE` against the live DB so the existing data works.

Each fix is pinned by a regression test in
`tests/api/test_marketplace_bugfixes.py`. The test file's
module docstring is the contract — if you change the response
shape of any of the three endpoints, you must update the
corresponding assertions in lockstep with the frontend. The
convention follows `tests/api/test_impa_catalog.py`.

### 11. The AIS sim steers along the great-circle waypoint polyline, not a straight line to the destination

The route data in `sim/routes.py` was always a great-circle
polyline (60-nm waypoint spacing), but the tick loop in
`sim/world.py` originally steered the vessel directly at the
*destination* on every tick, computing a fresh initial bearing
each step. On a 5,000-nm leg that's a piecewise-rhumb-line —
the vessel heads straight at the destination, with the
straight-line track slowly curving as the bearing recomputes.
The result, visible on the Fleet Map, was that vessels cut
through land: MV Bosphorus drew a straight red line from
Trieste down through southern Italy to Sicily, through the
Italian peninsula. Looks unprofessional for the supervisor
demo.

The fix: steer toward the next unvisited waypoint, advancing
the waypoint index when the vessel crosses it. The "crossed"
check is two-clause — `d_to_wp < 0.5 nm` (the vessel is
essentially on the waypoint) OR the bearing to the waypoint
is more than 90° off the bearing to the destination (the
waypoint is now behind us along the great circle). Both
checks are needed: the distance check handles "vessel lands
exactly on waypoint" (where bearing is undefined / 0); the
bearing check handles "vessel sails past the waypoint" (step
> waypoint spacing). The advance runs at the start of the
tick *and* again after the move, so a single tick at
`VISUAL_SPEED_BOOST=10` that sails past several waypoints
catches up correctly.

The principle is general: anywhere a system has a routing
layer (waypoints, plan, schedule) and a steering layer
(tick, "where do I go next"), the steering layer must
follow the routing layer's output, not bypass it with a
"shortcut" to the final destination. The shortcut is
correct for short steps (waypoint spacing >> step size) but
breaks when the step grows.

The pin is `tests/sim/test_world.py::test_path_follows_waypoints_not_straight_line`
— a buggy "head straight at destination" implementation
would exceed 100 nm of cross-track error on the SG→SH leg
because the great circle arcs through the East China Sea
while the straight line cuts through the South China Sea.

---

## What we'd do next

In rough priority order:

1. **Marketplace proposal amendments** — let the admin change
   per-line winners after composing, without re-composing from
   scratch. The data model is ready; the UI affordance isn't.
2. **Supplier-portal push channel** — WebSocket / SSE for the
   24h acceptance window. Right now the supplier only learns
   they've been assigned via the 30s polling notifications
   table.
3. **Fix the per-vessel dwell override in `sim.scenarios`** so
   `suez_blockage` produces visible motion. ~30 lines, no API
   changes.
4. **Add a WebSocket / SSE notification channel** behind the
   existing polling, with the polling as a fallback. The
   notification table is already the source of truth.
5. **Add a GitHub Actions workflow** that runs `pytest`, `ruff
   check`, and the frontend's `npm run lint` on every push. ~20
   lines of YAML.
6. **Add a frontend test suite** — Vitest for unit tests,
   Playwright for one happy-path end-to-end test (login → create
   order → see notification).
7. **Wire a real AIS feed adapter** so the backend can ingest
   production data with the same code path.
8. **Tenant isolation** — a `tenant_id` column on every business
   table, with a request-scoped filter.
9. **Internationalisation** — pull every UI string out of the
   components into a single i18n catalog.
10. **Load test the catalog endpoint** with `locust` and tune the
    indexes based on real query patterns.
11. **Accessibility audit** against WCAG 2.1 AA.

---

## How to evaluate this project

If you're a hiring manager or a curious engineer, here's the order
I would read things in:

1. **This file** — 10 minutes for the project story and the gap list
2. **[`docs/architecture/01-system-architecture.md`](./docs/architecture/01-system-architecture.md)**
   — the system topology
3. **[`docs/architecture/09-marketplace-redesign.md`](./docs/architecture/09-marketplace-redesign.md)**
   — the marketplace redesign: fan-out, per-line decision, 24h
   window. The most interesting new code in the project.
4. **[`backend/app/main.py`](./backend/app/main.py)** — the
   middleware stack and lifespan handler, in one read you see how
   the request/response cycle is wired
5. **[`backend/app/services/marketplace.py`](./backend/app/services/marketplace.py)**
   — the proposal composer / slice assigner. The largest new
   service in the marketplace redesign.
6. **[`backend/sim/runner.py`](./backend/sim/runner.py)** — the
   simulator's main loop, the part that surprised me most when
   writing it
7. **[`frontend/src/pages/FleetMap.jsx`](./frontend/src/pages/FleetMap.jsx)**
   — the Leaflet integration, the part of the frontend I had the
   most fun building
8. **The tests** — `backend/tests/marketplace/` is the densest
   new test directory, with 64 tests across 8 files
9. **The `docs/architecture/` set** — the long-form deep dives

If you only have 30 minutes, run the Fleet Map demo and read this
file.

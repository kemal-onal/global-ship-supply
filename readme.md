# AVS Global — Ship Supply & Logistics Operations Platform

> **A maritime ship-supply and logistics platform built end-to-end:**
> FastAPI + PostgreSQL backend, React 19 + Vite PWA frontend, and a
> standalone synthetic AIS traffic generator. VSAT-resilient offline
> ordering, multi-nationality catering provisioning, supplier bidding,
> customs regulation filtering, per-user notifications, and a live
> fleet map that plots vessel traffic from the simulator on a Leaflet
> world map.

![License: MIT](https://img.shields.io/badge/license-MIT-green)
![Backend: FastAPI 109](https://img.shields.io/badge/backend-FastAPI%20109-009688)
![Frontend: React 19 + Vite 6](https://img.shields.io/badge/frontend-React%2019%20%2B%20Vite%206-61dafb)
![Database: PostgreSQL 16](https://img.shields.io/badge/database-PostgreSQL%2016-336791)
![Cache: Redis 7](https://img.shields.io/badge/cache-Redis%207-dc382d)
![PWA: Service Worker](https://img.shields.io/badge/PWA-Service%20Worker-5a0fc8)
![Map: Leaflet 1.9](https://img.shields.io/badge/map-Leaflet%201.9-199900)
![Tests: 427 passing](https://img.shields.io/badge/tests-427%20passing-brightgreen)

## Highlights

- **Live Fleet Map** — Leaflet page at `/fleet-map` polls the
  simulator and plots vessel routes (polylines) and current positions
  (markers) in real time.
- **Offline-first ordering** — IndexedDB + Service Worker; the
  frontend queues orders when VSAT drops and replays them idempotently
  when it returns.
- **Multi-nationality catering** — provisioning plans computed from
  crew breakdown × voyage length × per-nationality calorie targets.
- **Supplier bidding with weighted comparison** — RFQ → quotes →
  `compare_quotes` with price / lead-time / reliability / quality
  scoring (weights tunable via env vars). Bid wars are **sealed**
  for non-admin callers (ranked "Bidder N" labels, winner's total
  and lead time only) — supplier identity and per-bidder prices
  are hidden until an admin commits the award.
- **Six-role RBAC with vessel scoping** — `super_admin`,
  `fleet_admin`, `vessel_captain`, `purchasing_officer`,
  `chief_steward`, and external `supplier` roles, each with a
  curated set of `resource:action:scope` permissions. A purchaser
  on vessel 0 cannot see RFQs belonging to vessel 1 — the API
  returns 404 (not 403) to avoid leaking resource existence.
- **Marketplace redesign** — replaces the sealed-bid auction with a
  fan-out RFQ, per-line supplier decision, admin-composed proposal,
  and a 24-hour supplier acceptance window. Purchasers see who
  wins which line; suppliers see only the lines they bid on; the
  market-sim auction is gone.
- **IMPA-first ordering** — order lines carry no price. The
  purchaser types a 6-digit IMPA code in `OrderCreate`, the typeahead
  resolves to a catalog row, and the supplier commit is "I can
  deliver this in the vessel's ETA→ETD window" before any per-line
  pricing. The clarification thread is the admin↔purchaser surface
  for handling ambiguity.
- **Supplier portal** — a dedicated supplier-facing page at
  `/supplier` that lists invited RFQs, lets the supplier accept
  or decline, and redacts vessel identity to "Vessel #N" via a
  CRC32 hash. Suppliers never see who the actual vessel is.
- **Customs & port regulation engine** — JSONLogic-lite evaluator over
  (order, country) → severity, blocking flag, permit requirement.
- **Per-user notifications** — server-side inbox + 30s polling badge +
  bell panel; triggered automatically on order state transitions.
- **Synthetic AIS traffic** — standalone `sim/` package decoupled
  from FastAPI/SQLAlchemy, with 4 built-in scenarios (Mediterranean
  shuttle, Suez blockage, North-Atlantic storm rerouting, quiet
  harbor). Vessels trace the great-circle waypoint polyline
  (not a straight line) and report wall-clock `event_ts`; the
  runner also exposes a `VISUAL_SPEED_BOOST=10` multiplier so
  you can see cross-ocean motion in minutes. Same feed your
  production data pipeline would consume.
- **427 passing tests** — pytest with `asyncio_mode = "auto"`;
  the marketplace redesign (proposal composer, supplier gate,
  preparation sweeper), IMPA-first catalog reader, clarification
  thread, RBAC permissions, the AIS sim (waypoint following,
  MMSI realignment, scenario integration), and the 3 marketplace
  bugfix regressions from 2026-09-07 each have their own test
  files. The full suite runs in ~13 s.

## Quick links

- **[`REPORT.md`](./REPORT.md)** — the project story: motivation,
  what we built, what's not done, what we'd do next. Read this if
  you're evaluating the project.
- **[`docs/architecture/`](./docs/architecture/)** — nine deep-dive
  documents on system topology, indexing, RBAC/security, offline-first,
  catering & RFQ, the Figma design system, the marketplace simulator,
  the sealed-bid / counter-offer classification model, and the
  marketplace redesign (fan-out, per-line decision, 24h window).
- **[`docs/auth-cookie-migration.md`](./docs/auth-cookie-migration.md)** — cookie-based JWT auth migration (supervisor instruction 2026-09-17, Fix A: cookie refresh with full roles).
- **[`possible_bugs.md`](./possible_bugs.md)** — 12 unsolved bugs documented 2026-09-17 (0 fixes applied today); P2 design tensions verified.
- **[`WORK_SUMMARY_2026-09-17.md`](./WORK_SUMMARY_2026-09-17.md)** — session work summary: P1 fixes (#1-6 verified), cookie auth migration, P3 fixes/docs, new bugs.
- **[`LICENSE`](./LICENSE)** — MIT.
- **Demo accounts** are listed in
  [Quickstart → Demo accounts](#demo-accounts-seeded) below.

## Table of contents

1. [Why we rebuilt it](#why-we-rebuilt-it)
2. [Repository layout](#repository-layout)
3. [Quickstart — Docker (recommended)](#quickstart--docker-recommended)
4. [Quickstart — local development (no Docker)](#quickstart--local-development-no-docker)
5. [Live Fleet Map](#live-fleet-map)
6. [API tour](#api-tour)
7. [AIS simulator](#ais-simulator)
8. [Marketplace redesign](#marketplace-redesign)
9. [Demo flows](#demo-flows)
10. [Demo gotchas](#demo-gotchas)
11. [Permissions & sealed bids](#permissions--sealed-bids)
12. [Notifications](#notifications)
13. [Troubleshooting](#troubleshooting)
14. [Testing](#testing)
15. [Production checklist](#production-checklist)
16. [Contributor notes](#contributor-notes)
17. [License](#license)

For the project story, design rationale, and what's next, see
[`REPORT.md`](./REPORT.md). For deep-dive docs, see
[`docs/architecture/`](./docs/architecture/).

---

## Why we rebuilt it

The original mock-up was a Flask + SQLite demo that could handle dozens of
rows. Production needs:

| Need                                              | What the new stack does                                                                                |
| ------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| Browse a **5,000-row IMPA/ISSA catalog** in <50ms | PostgreSQL `tsvector` + GIN indexes, B+tree indexes on SKU/price/category                              |
| **Offline ordering** when VSAT drops              | IndexedDB + Service Worker + replay engine with idempotency keys + conflict detection                  |
| **Auth** that survives IP changes at sea          | JWT (RS256) with 8-day access + 30-day refresh, RBAC with `resource:action:scope`                      |
| **Six-role RBAC with vessel scoping**             | Route-level `require_permission` + row-level `assert_vessel_access`; cross-vessel reads return 404     |
| **Sealed-bid RFQ** for non-admin callers          | Response-side redaction in `redaction.py` (`hides_prices` at deepest layer, line 76) + `rfq_serializers.py`; counter-offer terms classified `winner_only`          |
| **Marketplace redesign + simplified flow**          | `compose_proposal` + `supplier_accept_slice` (redesigned); `marketplace_simple.py` fan-out RFQ (simplified). Proposal endpoint (`GET /orders/{id}/proposal`) loads RFQ directly (no vessel gate at query), applies redaction (`hides_prices`) only at output stage. Admin and purchaser both see price + qty at proposal review. |
| **IMPA-first ordering**                           | Order line has no price; IMPA typeahead in `OrderCreate`; ETA/ETD delivery gate; clarification thread |
| **Supplier portal** with vessel redaction         | `GET /supplier-portal/rfqs`; suppliers see "Vessel #N" only; can-deliver-in-window gate before pricing |
| **IDS/IPS** at the perimeter                      | Brute-force counter, port-scan detector, SQL/XSS injection filter, structured security events          |
| **Per-nationality catering plans**                | Voyage algorithm: calorie targets × crew × days + buffer, menu templates per (nationality, meal_type)  |
| **Supplier bidding** with weighted comparison     | RFQ → quotes → `compare_quotes` with price/lead-time/reliability/quality scores                        |
| **Customs & port regulation** filter              | JSONLogic-lite condition evaluator over (order, country) → severity, blocking flag, permit requirement |
| **Per-user notifications**                        | Server-side inbox + 30s polling badge, in-app bell panel, mark-read/mark-all-read                     |
| **Modern UI** designed in Figma                   | Component-based, dark mode, TanStack-Virtual data grids, design tokens mirrored from Figma             |
| **Live synthetic AIS traffic** on a map           | Standalone `sim/` package, 4 scenarios, polled at 5s by a Leaflet map page. Vessels follow the great-circle waypoint polyline (not a straight line) and report wall-clock `event_ts` |

See `docs/architecture/` for the deep dives on each.

---

## Repository layout

What's actually in the repo today. Empty directories are omitted.

```
mock-up/
├── backend/                          # FastAPI service (Python 3.11/3.12)
│   ├── app/
│   │   ├── api/v1/                   # Routers — one file per resource
│   │   │   ├── auth.py               #   /auth/{login,refresh,logout,me}
│   │   │   ├── catalog.py            #   /catalog/{products,categories,impa,issa,stats,rfq-eligible}
│   │   │   ├── catering.py           #   /catering/{menus,nationalities,provisioning-plans,…}
│   │   │   ├── clarification.py      #   /orders/{id}/{clarify,clarify/answer,clarify/resolve}
│   │   │   ├── customs.py            #   /customs/{countries,rules,port-regulations,evaluate}
│   │   │   ├── dashboard.py          #   /dashboard/{overview,recent-orders,…}
│   │   │   ├── marketplace.py        #   /marketplace/{candidates,compose,approve} (per-line decision)
│   │   │   ├── notifications.py      #   /notifications (+ /unread-count, /{id}/read, /read-all)
│   │   │   ├── orders.py             #   /orders + /{id}/transition (fires notification on transition)
│   │   │   ├── ports.py              #   /ports (incl. /_/countries)
│   │   │   ├── rfq.py                #   /rfq/{for-order,quotes,compare}
│   │   │   ├── supplier_portal.py    #   /supplier-portal/{rfqs,rfqs/{id},rfqs/{id}/quote,quotes/{id}/accept,assignments}
│   │   │   ├── sync.py               #   /sync/{replay,queue,queues,conflicts}
│   │   │   ├── users.py              #   /users + /{id} + /me (via auth)
│   │   │   ├── vessels.py            #   /vessels + /{id}
│   │   │   └── internal/ais.py       #   /internal/ais/{ingest,positions,health}  (no-auth)
│   │   ├── core/                     # Settings, security, IDS/IPS, logging
│   │   ├── deps/auth.py              # `require_permission(...)`, `CurrentToken` dependency
│   │   ├── models/                   # ORM (one file per aggregate)
│   │   ├── services/                 # Business logic (no FastAPI imports)
│   │   ├── db/
│   │   │   ├── base.py               # SQLAlchemy declarative Base
│   │   │   ├── session.py            # async engine + session factory + health check
│   │   │   └── migrations/           # Alembic
│   │   │       └── versions/
│   │   │           ├── 0001_initial.py
│   │   │           ├── 0002_ais_position_reports.py
│   │   │           ├── 0003_market_sim_events.py
│   │   │           ├── 0004_market_sim_event_visibility.py
│   │   │           ├── 0005_marketplace_redesign.py
│   │   │           ├── 0006_marketplace_enums.py
│   │   │           ├── 0007_impa_first.py
│   │   │           └── 0008_auditaction_values.py
│   │   └── __main__.py               # `python -m app` shim
│   ├── sim/                          # Synthetic AIS data simulator (standalone)
│   │   ├── types.py                  #   Port, Vessel, Route, PositionReport, SimEvent
│   │   ├── geo.py                    #   Haversine, slerp, initial-bearing math (pure)
│   │   ├── ports.py                  #   54 hand-picked maritime hubs
│   │   ├── vessels.py                #   12 fictional vessels (MID 9xx MMSIs, mirrors seed fleet)
│   │   ├── routes.py                 #   Great-circle route generation
│   │   ├── world.py                  #   Tick loop, ship movement, port events
│   │   ├── events.py                 #   EventBatch (JSON adapter for /internal/ais/ingest)
│   │   ├── backend_client.py         #   Async httpx client (retry policy, health check)
│   │   ├── scenarios.py              #   4 built-in traffic scenarios + registry
│   │   ├── config.py                 #   SimSettings (SIM_ env prefix, 11 fields)
│   │   ├── runner.py                 #   CLI entry point: `python -m sim.runner`
│   │   └── __main__.py               #   `python -m sim` shim
│   ├── scripts/seed.py               # Idempotent demo seeder (5 users, suppliers, ports…)
│   ├── tests/
│   │   ├── api/internal/test_ais_ingest.py   #   10 tests — synthetic AIS ingest
│   │   ├── api/                              # 103 tests — RBAC, RFQ, IMPA catalog, redaction, marketplace bugfixes
│   │   ├── marketplace/                      # 101 tests — proposal composer, supplier gate, clarification thread, ETA snapshot, rfqs-for-compose
│   │   ├── market_sim/                       # 30 tests — dry-run bid war, counter-offer visibility (legacy)
│   │   └── sim/                              # 193 tests across 9 files — port/vessel/geo math, waypoint following, scenarios
│   ├── pyproject.toml                # Project + ruff + mypy + pytest config
│   ├── alembic.ini
│   ├── Dockerfile                    # Reused by `backend` and `sim` services
│   └── .env.example
│
├── frontend/                         # React 19 + Vite PWA
│   ├── src/
│   │   ├── api/client.js             # Auto-refresh JWT, ApiError class
│   │   ├── components/
│   │   │   ├── Layout.jsx            # Sidebar nav + header (theme/network/notifications/user)
│   │   │   └── NotificationsPanel.jsx # Bell dropdown — list, mark read, mark all read
│   │   ├── pages/                    # 18 page-level components
│   │   │   ├── Login.jsx  Dashboard.jsx  Catalog.jsx  ProductDetail.jsx
│   │   │   ├── Orders.jsx  OrderCreate.jsx  OrderDetail.jsx
│   │   │   ├── RFQ.jsx  Catering.jsx  Customs.jsx
│   │   │   ├── Ports.jsx  Vessels.jsx  FleetMap.jsx
│   │   │   ├── Marketplace.jsx  SupplierPortal.jsx  Permissions.jsx
│   │   │   ├── Sync.jsx  Settings.jsx
│   │   ├── store/                    # Zustand: auth, theme, network, notifications
│   │   ├── services/                 # Thin wrappers (e.g. notifications.js)
│   │   ├── offline/                  # IndexedDB (db.js) + sync engine (sync.js)
│   │   ├── App.jsx                   # Routes
│   │   └── main.jsx                  # Boot
│   ├── public/                       # favicon + icon sprite
│   ├── package.json                  # dev, build, preview, lint (no test scripts yet)
│   ├── tailwind.config.js
│   ├── vite.config.js                # Dev proxy: /api → :8000 (no rewrite!)
│   ├── Dockerfile
│   └── nginx.conf
│
├── infrastructure/
│   └── docker/
│       ├── docker-compose.yml        # postgres + redis + backend + sim + frontend
│       └── .env.example
│
├── docs/architecture/                # 9 deep-dive docs
│   ├── 01-system-architecture.md     #   high-level topology
│   ├── 02-indexing.md                #   catalog FTS + indexes
│   ├── 03-rbac-security.md           #   auth + IDS/IPS
│   ├── 04-offline-first.md           #   IndexedDB + replay
│   ├── 05-catering-rfq.md            #   catering algorithm + RFQ scoring
│   ├── 06-figma-design-system.md     #   design tokens
│   ├── 07-marketplace-sim.md         #   sealed-bid simulator (legacy)
│   ├── 08-rbac-and-sealed-bidding.md #   RBAC + counter-offer classification
│   └── 09-marketplace-redesign.md    #   fan-out + per-line + 24h window (replaces 07)
│
└── readme.md                         # ← you are here
```

> The previous `app/schemas/`, `app/utils/`, `frontend/src/{services,types,utils,hooks}` (except `services/notifications.js`),
> `infrastructure/k8s/`, `shared/types/`, and `frontend/src/components/{data-grid,forms,ui}/` directories
> are placeholder scaffolding that have since been inlined (routers own their Pydantic models)
> or removed. They are intentionally omitted from this listing.

---

## Quickstart — Docker (recommended)

The fastest way to a running stack:

```bash
cd infrastructure/docker
cp .env.example .env             # edit if you want different ports
docker compose up --build
```

What you get (5 services):

| Service     | URL / Port              | Notes                                                       |
| ----------- | ----------------------- | ----------------------------------------------------------- |
| Frontend    | http://localhost:5173   | Vite-built static assets served by nginx                    |
| Backend API | http://localhost:8000   | Swagger at `/docs`, ReDoc at `/redoc`, OpenAPI at `/openapi.json` |
| Backend ops | http://localhost:8000/health, /metrics | Health probe + Prometheus metrics (no auth)     |
| AIS sim     | — (outbound only)       | Synthetic vessel traffic; see [AIS simulator](#ais-simulator) |
| Postgres    | localhost:5432          | `avs / avs-dev-password` (dev)                              |
| Redis       | localhost:6379          | Optional in dev; IDS/IPS falls back to in-process counters  |

On first boot the backend runs `alembic upgrade head` then
`scripts/seed.py --skip-if-populated` so you have demo data ready.

### Demo accounts (seeded)

The login form accepts **email or username** on the `username` field of
the OAuth2 form. The seed creates these accounts:

| Email                       | Username    | Password   | Role                 | Vessel | Notes |
| --------------------------- | ----------- | ---------- | -------------------- | ------ | ----- |
| `admin@avsglobal.com`       | `admin`     | `admin123` | `super_admin`        | —      | full access; can compose marketplace proposals |
| `fleetadmin@avsglobal.com`  | `fleet`     | `demo123`  | `fleet_admin`        | —      | same as admin, scoped to the fleet |
| `captain@avsglobal.com`     | `captain`   | `demo123`  | `vessel_captain`     | 0      | vessel-side read |
| `purchasing@avsglobal.com`  | `purchaser` | `demo123`  | `purchasing_officer` | 0      | creates orders; approves proposals |
| `steward@avsglobal.com`     | `steward`   | `demo123`  | `chief_steward`      | 0      | catering + clarification thread |
| `supplier1@avsglobal.com`   | `supplier1` | `demo123`  | `supplier`           | —      | Rotterdam — only one seeded here |
| `supplier2@avsglobal.com`   | `supplier2` | `demo123`  | `supplier`           | —      | Singapore — best for the marketplace demo |
| `supplier3@avsglobal.com`   | `supplier3` | `demo123`  | `supplier`           | —      | Dubai |
| `info@apcmarine.sg`         | `apcmarine` | `demo123`  | `supplier`           | —      | APC Marine (Singapore) — third-party demo supplier |

**Change in prod.** The default super-admin password (`admin123`) is
the one account that's *not* `demo123` — keep it out of any non-dev
environment.

---

## Quickstart — local development (no Docker)

If you'd rather run each piece directly. Tested on Windows 11 + macOS.

### 0. Prerequisites

- **Python 3.11 or 3.12** (3.13+ breaks the pinned `pydantic==2.5.3` /
  `asyncpg==0.29.0` toolchain in `pyproject.toml`)
- **PostgreSQL 16** reachable on `localhost:5432`
- **Node 20+** for the frontend
- Redis is **optional** — the IDS/IPS counters fall back to in-process state

### 1. Database (PostgreSQL 16)

The app expects a database called `avs` owned by a role `avs` with
password `avs-dev-password`. Create them once:

**macOS / Linux**
```bash
brew install postgresql@16
brew services start postgresql@16
createuser -s avs             # or: sudo -u postgres createuser -s avs
createdb -O avs avs
psql -c "ALTER USER avs WITH PASSWORD 'avs-dev-password';"
```

**Windows (PowerShell, as Administrator)**
```powershell
# Easiest: winget
winget install PostgreSQL.PostgreSQL.16

# If the EDB installer silently skips cluster init (it does on some
# Turkish-locale Windows boxes), do it manually in PowerShell:
$env:PGDATA = "C:\Program Files\PostgreSQL\16\data"
& "C:\Program Files\PostgreSQL\16\bin\initdb.exe" -D $env:PGDATA -U postgres --locale=C --encoding=UTF8
& "C:\Program Files\PostgreSQL\16\bin\pg_ctl.exe" -D $env:PGDATA start

# Then create the role + db (run as the postgres superuser):
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -c "CREATE USER avs WITH PASSWORD 'avs-dev-password' SUPERUSER;"
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -c "CREATE DATABASE avs OWNER avs;"
```

### 2. Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\Activate.ps1
pip install -e .[dev]                # installs runtime + pytest/ruff/mypy
cp .env.example .env
# On Windows, also ensure .env has:
#   ENVIRONMENT=development
#   DATABASE_URL=postgresql+asyncpg://avs:avs-dev-password@localhost:5432/avs
#   SYNC_DATABASE_URL=postgresql+psycopg2://avs:avs-dev-password@localhost:5432/avs

alembic upgrade head
python -m scripts.seed --skip-if-populated
uvicorn app.main:app --reload --port 8000
```

> **First-boot one-shot SQL:** migration `0001_initial` creates the
> `unitofmeasure` Postgres enum *without* the `pail` variant that
> the seed uses. Run this once, in any order after `alembic upgrade head`:
> ```sql
> ALTER TYPE unitofmeasure ADD VALUE IF NOT EXISTS 'pail';
> ```
> See [Troubleshooting](#invalid-input-value-for-enum-unitofmeasure-pail).

**Windows tip:** the seed script and uvicorn print a Unicode banner
(`→`, `✅`). On Windows consoles with a non-UTF8 codepage you'll see
`UnicodeEncodeError`. Run them with UTF-8 mode:

```powershell
$env:PYTHONUTF8 = 1
python -m scripts.seed
```

The API is now at `http://localhost:8000`. Useful endpoints:

- `/docs` — Swagger UI
- `/redoc` — ReDoc UI
- `/openapi.json` — machine-readable spec
- `/health` — DB-reachable liveness (no auth)
- `/metrics` — Prometheus exposition (no auth)

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

The app is at `http://localhost:5173`. Vite proxies `/api/*` to the
backend on `localhost:8000` — the proxy must pass the `/api` prefix
through (do **not** strip it). If you see a `Not Found` toast on the
login screen, that's the symptom: check `frontend/vite.config.js` and
make sure the proxy entry has no `rewrite` that strips `/api`.

### 4. (Optional) AIS simulator

Either start it from Docker (`docker compose up -d sim`) or run it
locally — see [AIS simulator](#ais-simulator) for the full guide.

---

## Live Fleet Map

The frontend ships a Leaflet-based map at **`/fleet-map`** (sidebar: "Live Fleet Map")
that plots the simulator's synthetic vessel traffic on a world map. It
works **without the simulator** (you'll see an empty-state message) and
shows live motion the moment a sim is running.

What it does:

- Polls `GET /api/v1/internal/ais/positions?scenario=…&event_type=position_report&limit=1000`
  every 5 s (no auth required; the extra bearer header is ignored)
- Groups rows by MMSI and draws:
  - A **colored polyline** through the vessel's historical positions (the route)
  - A **circleMarker** at the vessel's latest position
  - A **tooltip** on click with name, MMSI, SOG, COG, nav status, last update
- A scenario dropdown (default_med / suez_blockage / storm_rerouting / quiet_harbor)
  refetches with the new filter
- A "Center" button fits the map to all current positions
- A bottom-left fleet panel lists every vessel with current SOG

The map tile layer is OpenStreetMap; Leaflet CSS is loaded from
`cdn.jsdelivr.net` in `frontend/index.html` and the JS is bundled by
Vite from the local `leaflet@1.9.4` dependency (added to
`frontend/package.json`).

To see vessels moving, start the sim. See [AIS simulator](#ais-simulator).

> **Smoothness tradeoff.** The map polls every 5 seconds, so motion
> only *looks* fluid if the sim advances slowly enough that a vessel
> takes at least 5–10 wall-seconds to traverse a leg. In practice that
> means `SIM_SIM_TIME_SCALE` between `60` (1 wall-sec = 1 sim-min) and
> `600` (1 wall-sec = 10 sim-min). At higher scales a leg completes
> before the next poll and the markers "pop" between waypoints; the
> trail still grows correctly, but the *animation* is choppy.

> **Heads-up — `suez_blockage` doesn't move.** This scenario sets
> `port_dwell_minutes=10_000_000` globally on the world config, so
> every vessel sits at berth for ~19 years of sim time. You'll see
> the 6 markers at their starting ports (Singapore, Shanghai, Mundra,
> Malta, Algeciras) and the same `sog=0` report every 2 s. To see
> actual routes forming, run `default_med` instead. The bug is
> documented in `backend/sim/scenarios.py:181` (a future per-vessel
> dwell override would clean it up).

---

## API tour

All paths are relative to `http://localhost:8000` and prefixed with
`/api/v1` unless otherwise noted.

### Auth (public)

| Method | Path                | Purpose                                            |
| ------ | ------------------- | -------------------------------------------------- |
| POST   | `/auth/login`       | OAuth2 password grant; returns JWT pair            |
| POST   | `/auth/refresh`     | Rotate the refresh token                           |
| POST   | `/auth/logout`      | Invalidate the current session                     |
| GET    | `/auth/me`          | Current user profile (bearer)                      |

### Users

| Method | Path              | Auth        | Purpose                                |
| ------ | ----------------- | ----------- | -------------------------------------- |
| GET    | `/users`          | `user:read` | User directory (admin only)            |
| GET    | `/users/{id}`     | bearer      | User detail (self or admin)            |

### Fleet & geography

| Method | Path                                | Auth   | Purpose                                                |
| ------ | ----------------------------------- | ------ | ------------------------------------------------------ |
| GET    | `/vessels`                          | bearer | Fleet listing                                          |
| GET    | `/vessels/{id}`                     | bearer | Vessel detail                                          |
| GET    | `/ports`                            | bearer | World port network (filter `country`, `status`, `q`)  |
| GET    | `/ports/_/countries`                | bearer | Distinct countries for the port list                   |
| GET    | `/ports/{id}`                       | bearer | Port detail                                            |

### Catalog

| Method | Path                          | Auth   | Purpose                                              |
| ------ | ----------------------------- | ------ | ---------------------------------------------------- |
| GET    | `/catalog/products`           | bearer | FTS + faceted filter (`q`, `category`, `min_price`, `max_price`, `in_stock`) |
| GET    | `/catalog/products/{id}`      | bearer | Product detail with specs, cross-references          |
| GET    | `/catalog/categories`         | bearer | Product category tree                                |
| GET    | `/catalog/impa`               | bearer | IMPA code cross-reference                            |
| GET    | `/catalog/issa`               | bearer | ISSA code cross-reference                            |
| GET    | `/catalog/stats`              | bearer | Catalog KPIs                                         |

### Orders

| Method | Path                            | Auth            | Purpose                                            |
| ------ | ------------------------------- | --------------- | -------------------------------------------------- |
| GET    | `/orders`                       | bearer          | Order list with status/date filters                |
| POST   | `/orders`                       | `order:create`  | Create order (IMPA-first, runs customs evaluation) |
| GET    | `/orders/{id}`                  | bearer          | Order with items + RFQ list                        |
| POST   | `/orders/{id}/transition`       | `order:write`   | Drive state machine (emits a `Notification` to the assignee — see [Notifications](#notifications)) |

### Clarification thread

The admin↔purchaser surface for handling ambiguous order details. Each
entry has a `question`, an optional `answer`, and a `resolved_at`
timestamp. Entries are append-only; both sides see the full thread.

| Method | Path                                    | Auth                  | Purpose                                            |
| ------ | --------------------------------------- | --------------------- | -------------------------------------------------- |
| POST   | `/orders/{id}/clarify`                  | `marketplace:clarify` | Admin asks a question (flips order to `awaiting_clarification`) |
| GET    | `/orders/{id}/clarify`                  | bearer                | Read the full thread                               |
| POST   | `/orders/{id}/clarify/answer`           | `marketplace:clarify` | Purchaser replies (flips order back to `quoting`)  |
| POST   | `/orders/{id}/clarify/resolve`          | `marketplace:clarify` | Mark an entry resolved                             |

### RFQ

| Method | Path                                  | Auth             | Purpose                                          |
| ------ | ------------------------------------- | ---------------- | ------------------------------------------------ |
| GET    | `/rfq`                                | bearer           | RFQ list                                         |
| POST   | `/rfq/for-order/{order_id}`           | `rfq:create`     | Build RFQ to suppliers at destination port       |
| GET    | `/rfq/{rfq_id}`                       | bearer           | RFQ detail with all quotes                       |
| POST   | `/rfq/quotes`                         | `quote:create`   | Supplier submits a quote                         |
| POST   | `/rfq/{rfq_id}/compare`               | `rfq:award`      | Weighted bid comparison (legacy — kept for backward compat) |

### Marketplace (proposal composer)

The replacement for the sealed-bid auction. The admin collects per-line
quotes, picks a winning supplier per line, composes a proposal, and
the purchaser approves it. After approval, the assigned suppliers get a
24-hour window to accept.

| Method | Path                                              | Auth                    | Purpose                                            |
| ------ | ------------------------------------------------- | ----------------------- | -------------------------------------------------- |
| GET    | `/marketplace/orders/{id}/candidates`             | `marketplace:compose`   | Per-line candidate suppliers with their best quote |
| POST   | `/marketplace/orders/{id}/compose`                | `marketplace:compose`   | Compose the proposal (one slice per line)          |
| POST   | `/marketplace/orders/{id}/approve`                | `marketplace:approve`   | Purchaser approves — creates `SupplierLineAssignment` rows and starts the 24h timer |
| GET    | `/marketplace/orders/{id}`                        | bearer                  | Current proposal + slice state                     |

### Supplier portal

The supplier-facing API. The supplier is authenticated as a regular
`supplier` user; the route resolves them to a `Supplier` row by matching
`User.email == Supplier.contact_email`. Vessel identity is redacted to
`"Vessel #N"` (CRC32 of vessel id) in every response.

| Method | Path                                                  | Auth                       | Purpose                                            |
| ------ | ----------------------------------------------------- | -------------------------- | -------------------------------------------------- |
| GET    | `/supplier-portal/rfqs`                               | `supplier_portal:view`     | RFQs the supplier is invited to                    |
| GET    | `/supplier-portal/rfqs/{rfq_id}`                      | `supplier_portal:view`     | RFQ detail (with vessel label, not vessel name)    |
| POST   | `/supplier-portal/rfqs/{rfq_id}/quote`                | `supplier_portal:quote`    | Submit a quote; payload includes the IMPA-first `can_deliver_in_window` gate |
| POST   | `/supplier-portal/quotes/{quote_id}/accept`           | `supplier_portal:accept`   | Supplier accepts their assigned slices             |
| GET    | `/supplier-portal/assignments`                        | `supplier_portal:view`     | The supplier's post-approval slice list            |

### Catering

| Method | Path                                          | Auth             | Purpose                                    |
| ------ | --------------------------------------------- | ---------------- | ------------------------------------------ |
| GET    | `/catering/nationalities`                     | bearer           | Crew nationality profiles (kcal, macros)   |
| GET    | `/catering/menus`                             | bearer           | Menu templates                             |
| GET    | `/catering/provisioning-plans`                | bearer           | Saved provisioning plans                   |
| GET    | `/catering/provisioning-plans/{plan_id}`      | bearer           | Single plan                                |
| POST   | `/catering/provisioning-plans`                | `catering:plan`  | Save a computed plan                       |
| POST   | `/catering/compute-targets`                   | `catering:plan`  | Compute per-nationality calorie targets    |
| POST   | `/catering/plan`                              | `catering:plan`  | Compute provisioning basket for a voyage   |

### Customs & regulations

| Method | Path                                  | Auth            | Purpose                                          |
| ------ | ------------------------------------- | --------------- | ------------------------------------------------ |
| GET    | `/customs/countries`                  | bearer          | Country list (regulatory info)                   |
| GET    | `/customs/evaluate/{order_id}`       | `customs:eval`  | Re-evaluate an order against country rules       |
| GET    | `/customs/rules`                      | bearer          | Customs rules (filter `country`, `category`)     |
| GET    | `/customs/port-regulations`           | bearer          | Port-specific regulations                        |

### Sync (offline replay)

| Method | Path                | Auth   | Purpose                                          |
| ------ | ------------------- | ------ | ------------------------------------------------ |
| POST   | `/sync/replay`      | bearer | Drain offline action queue (idempotent)          |
| GET    | `/sync/queue`       | bearer | Per-user server-side queue status                |
| GET    | `/sync/queues`      | bearer | Aggregate queue status (admin)                   |
| GET    | `/sync/conflicts`   | bearer | Unresolved sync conflicts                        |

### Notifications

| Method | Path                       | Auth   | Purpose                                                                  |
| ------ | -------------------------- | ------ | ------------------------------------------------------------------------ |
| GET    | `/notifications`           | bearer | List the current user's notifications, newest first (`limit`, `offset`, `unread_only`) |
| GET    | `/notifications/unread-count` | bearer | Just the count — polled by the frontend bell badge every 30 s            |
| PATCH  | `/notifications/{id}/read` | bearer | Mark one notification as read (idempotent, 404 if not yours)             |
| PATCH  | `/notifications/read-all`   | bearer | Mark every unread notification as read; returns `{updated: N}`          |

### Dashboard

| Method | Path                                  | Auth   | Purpose                                  |
| ------ | ------------------------------------- | ------ | ---------------------------------------- |
| GET    | `/dashboard/overview`                 | bearer | Aggregated KPIs for the home page        |
| GET    | `/dashboard/recent-orders`            | bearer | Latest orders                            |
| GET    | `/dashboard/vessels-by-status`        | bearer | Fleet status breakdown                   |
| GET    | `/dashboard/quote-leaderboard`        | bearer | Top suppliers by quote score             |

### Internal — synthetic AIS ingest (no auth)

These endpoints back the `sim/` simulator. They are intentionally
**unauthenticated** because they're meant to run over a private
docker network. In production you would put them behind a firewall
or remove the `internal/` router entirely.

| Method | Path                          | Auth   | Purpose                                            |
| ------ | ----------------------------- | ------ | -------------------------------------------------- |
| POST   | `/internal/ais/ingest`        | none   | Bulk-ingest position reports and events            |
| GET    | `/internal/ais/positions`     | none   | Query ingested rows (filter by MMSI, scenario…)    |
| GET    | `/internal/ais/health`        | none   | Liveness for the ingest pipeline                   |

### Ops (no auth)

| Method | Path        | Purpose                                  |
| ------ | ----------- | ---------------------------------------- |
| GET    | `/health`   | DB-reachable liveness                    |
| GET    | `/metrics`  | Prometheus exposition                    |
| GET    | `/docs`     | Swagger UI                               |
| GET    | `/redoc`    | ReDoc UI                                 |
| GET    | `/openapi.json` | OpenAPI 3.1 schema                    |

---

## AIS simulator

The `backend/sim/` package is a **synthetic AIS data source** for the
backend. It generates realistic-shaped vessel position reports and
POSTs them to `/api/v1/internal/ais/ingest`, populating the
`ais_position_reports` table. Useful for:

- demoing the platform without paying for a real AIS feed,
- reproducing specific traffic patterns (storms, canal closures) on demand,
- stress-testing the ingest endpoint at high event rates.

The simulator is **decoupled from FastAPI/SQLAlchemy** — it has no
dependency on the backend's models, sessions, or settings. It can be
developed, unit-tested, and run independently. All identifiers it
emits (MMSI, IMO) use the **MID 9xx range** (unassigned by the ITU)
so any value reaching the backend is obviously synthetic.

### Built-in scenarios

| Name               | Vessels | Description                                                                                  |
| ------------------ | ------- | -------------------------------------------------------------------------------------------- |
| `default_med`      | 5       | Mediterranean short-sea shuttle: Piraeus, Genoa, Malta, Algeciras (the default scenario)      |
| `suez_blockage`    | 6       | Suez Canal closed — Asia↔Europe detours via the Cape of Good Hope; Med tankers idle at berth  |
| `storm_rerouting`  | 5       | North Atlantic storm forces traffic south via Tangier-Med (Morocco) instead of great-circle  |
| `quiet_harbor`     | 2       | 2 vessels on a 2-port loop (Rotterdam ↔ Hamburg); smoke test, minimal traffic                |

> **Known issue — `suez_blockage` dwell time.** The scenario sets
> `port_dwell_minutes=10_000_000` on the global `WorldConfig` to keep
> the Med tankers moored. Because the field is global, the Cape-route
> vessels also wait that long before departing. In practice the
> `suez_blockage` scenario never produces visible motion — use
> `default_med` if you want to see polylines forming on the Fleet Map.
> The fix is a per-vessel dwell override; see the comment at
> `backend/sim/scenarios.py:181`.

### Running with Docker

The `sim` service starts automatically with `docker compose up`. It
depends on `backend: service_healthy` and points at it over the
docker network:

```bash
cd infrastructure/docker
docker compose up -d sim
docker logs -f avs-sim
```

To switch scenarios at runtime, set `SIM_SCENARIO` in
`infrastructure/docker/.env`:

```bash
# .env
SIM_SCENARIO=suez_blockage
SIM_SIM_TIME_SCALE=120            # 1 wall-clock second = 2 sim-minutes
SIM_FLUSH_INTERVAL_SECONDS=5
```

Then `docker compose up -d sim` and the new scenario takes effect.

### Running locally (no Docker)

With the backend running on `localhost:8000`:

```bash
cd backend
.venv\Scripts\Activate.ps1        # or: source .venv/bin/activate

# Quick smoke test — 30 ticks, 1 wall-second = 1 sim-second by default
python -m sim.runner --scenario quiet_harbor --max-iterations 30

# Visible motion on the Fleet Map (1 wall-second = 10 sim-minutes)
$env:SIM_SIM_TIME_SCALE = 600      # PowerShell
python -m sim.runner --scenario default_med --max-iterations 200
```

Useful flags (all CLI flags override their `SIM_*` env equivalents):

| Flag                  | Purpose                                                                |
| --------------------- | ---------------------------------------------------------------------- |
| `--scenario NAME`     | Which built-in scenario to run (see table above)                       |
| `--seed N`            | Override the RNG seed for reproducible runs                            |
| `--backend-url URL`   | Override `SIM_BACKEND_URL` (default `http://localhost:8000`)           |
| `--max-iterations N`  | Stop after N ticks (0 = run until interrupted)                         |
| `--dry-run`           | Tick the world but never POST to the backend (logs each batch instead) |
| `--log-json`          | Emit logs as JSON lines (for log aggregators)                          |
| `--log-level LEVEL`   | Override `SIM_LOG_LEVEL` (default `INFO`)                              |
| `--list-scenarios`    | Print all registered scenarios and exit                                |

### Configuration

`SimSettings` reads from `SIM_*` env vars (see `backend/sim/config.py`,
11 fields: `backend_url`, `ingest_path`, `request_timeout_seconds`,
`max_batch_size`, `flush_interval_seconds`, `tick_seconds`,
`sim_time_scale`, `scenario`, `seed`, `log_level`, `log_json`). You
can also point it at a dotenv file with `SIM_ENV_FILE=path/to/.env`.

> **The CLI has no `--sim-time-scale` flag** — that setting is env-only.
> If you want to change it without editing `.env`, set
> `SIM_SIM_TIME_SCALE` in the same shell that runs the sim.

### What gets persisted

Every position report and event lands in `ais_position_reports` with
the run's `scenario`, `seed`, and `source='sim'` tag. To filter
synthetic data out of any query: `WHERE source = 'sim'`.

To see the simulator's output in real time:

```bash
docker exec -it avs-postgres psql -U avs -d avs -c "
  SELECT scenario, event_type, COUNT(*)
  FROM ais_position_reports
  WHERE source = 'sim'
  GROUP BY scenario, event_type
  ORDER BY scenario, event_type;
"
```

Or open the **Live Fleet Map** in the frontend — it shows the same
data, grouped by vessel, with current positions and routes.

### Architecture

| Module              | Responsibility                                                              |
| ------------------- | --------------------------------------------------------------------------- |
| `sim.types`         | Frozen dataclasses: `Port`, `Vessel`, `Route`, `PositionReport`, `SimEvent` |
| `sim.geo`           | Haversine, slerp, initial-bearing math (pure functions, no I/O)             |
| `sim.ports`         | 54 hand-picked maritime hubs (UN/LOCODE-keyed)                              |
| `sim.vessels`       | 12 fictional vessels (MID 9xx MMSIs, mirroring the seed fleet)             |
| `sim.routes`        | `build_route`, `build_circular_route` — great-circle math                   |
| `sim.world`         | Tick loop. `World.step()` yields `(PositionReport, [SimEvent])` per vessel; vessels follow the great-circle waypoint polyline, not a straight line |
| `sim.events`        | `EventBatch` — JSON adapter that produces the `IngestBatchIn` shape         |
| `sim.backend_client`| Async HTTP client (httpx) with retry policy + health check                 |
| `sim.config`        | `SimSettings` (pydantic-settings, `SIM_` env prefix)                        |
| `sim.scenarios`     | Frozen `Scenario` registry with `get_scenario(name)` lookup                 |
| `sim.runner`        | CLI entry point; drives the world, batches events, flushes to backend       |

### Great-circle waypoint following

Vessels don't move in a straight line from origin to destination — that
would have them cut through land on long ocean legs. The route data
already contains a great-circle polyline (60-nm waypoint spacing in
`sim/routes.py`); the tick loop in `sim/world.py` steers each vessel
toward the *next unvisited waypoint*, advancing when the waypoint is
either within 0.5 nm of the vessel or more than 90° off the bearing
to the destination. The advance runs both before and after the move
so a single tick that sails past several waypoints catches up
correctly. The result is a polyline that traces the great-circle arc
(through the East China Sea, around the Horn, etc.) rather than a
straight-line shortcut through land.

`tests/sim/test_world.py::test_path_follows_waypoints_not_straight_line`
pins this — it runs SG → SH and asserts every position stays within
50 nm of the great-circle interpolation between the two ports.

### Decoupled sim-time and wall-clock timestamps

`PositionReport.event_ts` is wall-clock UTC (`datetime.utcnow()` at tick
time), not sim-time. The two clocks are intentionally decoupled so the
backend can read "when did the vessel *actually* report" without
muddling it with "how much sim time has elapsed". A
`(event_ts - wall_clock) <= 5s` invariant is enforced in
`tests/sim/test_world.py::test_report_ts_is_wall_clock_within_5_seconds`.

### Speeding up the visual

`VISUAL_SPEED_BOOST` is a module-level constant in `sim/world.py`
(currently set to `10.0`). It multiplies per-tick distance, not SOG,
so reported COG and SOG stay realistic while the vessel covers ground
faster. The effect: a 3,000-nm leg that would normally take an hour
to play out in real-time becomes 5–10 minutes. This is what you want
when demoing to a stakeholder. Combine it with
`SIM_SIM_TIME_SCALE=60` for the smoothest visible motion.

The simulator's design and the rationale behind the
`source` column / no-FK isolation are documented in
`backend/app/models/ais.py` and `backend/app/api/v1/internal/ais.py`.

---

## Marketplace redesign

The sealed-bid auction is gone. The new flow is **fan-out → per-line
decision → 24-hour acceptance window**:

1. **Admin sends the order to suppliers.** `POST /orders/{id}/transition`
   with action `send_to_suppliers` flips the status from `draft` to
   `quoting` and writes a `RFQ` row whose `extra->'invited_supplier_ids'`
   lists the invited suppliers.
2. **Each supplier opens `/supplier`.** They see the RFQ, decide
   *"can I deliver this in the vessel's ETA→ETD window?"* (the
   IMPA-first gate), and either accept-and-price every line or
   decline with a reason. No price is sent until the gate is
   resolved.
3. **Admin opens `/marketplace`.** For each line, they see the
   candidate suppliers with their price / lead time / score and pick
   a winner. `POST /marketplace/orders/{id}/compose` writes a
   `SupplierProposal` with one `SupplierLineAssignment` per line.
4. **Purchaser opens `/orders/{id}`.** They see the proposal
   summary, click **Approve**, and the status flips to `confirmed`.
   Each assigned supplier gets a 24h window to confirm
   (`POST /supplier-portal/quotes/{id}/accept`).
5. **Sweeper.** A background task in the backend's lifespan
   (`sweep_preparation_timeouts`) drops suppliers who didn't
   confirm in 24h and re-broadcasts their slice to the next-ranked
   supplier. The sweep is the only thing in this flow that runs
   without a click.

The full design — schema, status model, redaction invariants, the
24h sweeper — is in
[`docs/architecture/09-marketplace-redesign.md`](./docs/architecture/09-marketplace-redesign.md).

### IMPA-first ordering

Order lines no longer carry a price. The purchaser types a 6-digit
IMPA code in `OrderCreate`, the typeahead resolves to a catalog
row, and the supplier's first commit is the ETA/ETD window check
*before* any per-line pricing. The reasoning is documented in the
`IMPA-first` redesign deep-dive (currently in `docs/architecture/`
under development; see [REPORT.md](./REPORT.md) for the rationale).

The admin↔purchaser **clarification thread** is the surface for
handling ambiguity (e.g. *"32-inch TV: OLED or QLED?"*). It's
appended to the order detail page; both sides see the same view.

### Supplier portal redaction

Suppliers never see the vessel's real name. The redaction in
`backend/app/services/redaction.py` is a CRC32 of the vessel id
modulo 1000 — stable across requests for the same vessel,
opaque across vessels. The supplier sees `"Vessel #438"` and
nothing else; the ETA/ETD window is exposed in the RFQ detail
so the supplier can decide "can I deliver in time" without
needing to know who the vessel is.

---

## Demo flows

### 1. Order flow

```
1. Log in as "purchasing@avsglobal.com" / "demo123"
2. /orders → "New order"
3. Pick a vessel and a port
4. Add 2–3 products from the right-hand picker
5. Submit
6. /orders/{id} → see customs evaluation, status = draft
7. Click "Submit for approval" → status = pending_approval
   (only `pending_approval` orders are RFQ-eligible; the RFQ page's
   order picker filters to this status)
8. Then click "Send RFQ to suppliers" → status = rfq_in_progress
9. (Log in as the order's assigned_to user) → bell badge increments
   → open it → see "Order ORD-… is now rfq in progress"
```

### 2. Offline flow

```
1. DevTools → Network → Offline
2. /catalog → see cached products, search works
3. /orders/new → build an order → submit
   → toast: "Offline: order queued and will sync when VSAT returns"
4. /sync → see the pending action
5. DevTools → Network → Online
6. /sync → action drains, row disappears
```

### 3. Catering flow

```
1. Log in as "steward@avsglobal.com" / "demo123"
2. /catering → pick a vessel
3. Set crew breakdown (Filipino: 12, Indian: 8, European: 4)
4. Set voyage start today + end in 14 days
5. Click "Generate plan"
6. See aggregated provisioning basket with estimated cost
```

### 4. RFQ flow

```
1. /rfq → pick a pending-approval order → "Send RFQ"
   (the new RFQ row appears with status = `sent`; eligible suppliers
   at the destination port receive email invitations with private
   quote links)
2. (As a supplier) — out of scope for the UI in this MVP — submit a quote
3. Back as purchaser → /rfq → click "Compare bids"
4. See ranked quotes with weighted scores
```

### 5. AIS simulator flow

```
1. python -m sim.runner --scenario default_med --max-iterations 1000
   (or via Docker: docker compose up -d sim)
2. Open /fleet-map → 5 colored markers at Piraeus / Genoa / Malta / Algeciras
3. After ~30s at the default 1x time-scale, the markers start moving
   and leave colored polylines
4. Switch to "Suez Blockage" in the dropdown → query refetches with
   the new filter, 6 markers at Asia / Med ports (note: the suez
   scenario never produces motion — see the heads-up below)
5. To stop the sim gracefully: Ctrl-C, or wait for `--max-iterations`
   to be reached. Without the cap (`--max-iterations 0`) the sim
   runs until interrupted
6. Inspect position reports for one vessel in psql:
   SELECT event_ts, lat, lon, sog, cog
   FROM ais_position_reports
   WHERE mmsi = '901000001' AND event_type = 'position_report'
   ORDER BY event_ts DESC LIMIT 10;
```

---

## Demo gotchas

A few things that surprised us the first time we walked through the
demo. Skim this before a live walkthrough.

### `draft` orders are not RFQ-eligible

A freshly created order sits in `draft` until you click **Submit for
approval** on the order detail page. This is intentional (so the
purchaser can iterate on a draft without spamming suppliers) but
nothing in the UI shouts at you about it. The marketplace flow
starts from `pending_approval` (or `awaiting_clarification`, if
the admin asked a question first).

### Rotterdam only has one eligible supplier in the seed

`/catalog/rfq-eligible` (and therefore the "X bid-eligible" pill in
the order-create picker) only counts suppliers that have a
`SupplierPort` row for the destination port. Rotterdam's seed data
only has one supplier there, so orders going to Rotterdam won't
generate a competitive bid war. For the demo, pick a port with
3+ eligible suppliers — Singapore, Hamburg, Piraeus, Algeciras all
work.

### 1-product orders only get 1 bid

`SupplierQuote` has a `UniqueConstraint("rfq_id", "supplier_id")` —
one bid per supplier per RFQ, ever. The marketplace simulator
respects this. Add 2–3 products to an order for a richer leaderboard
that actually shows the per-line decision doing something interesting.

### Supplier login is by `User.email`, not by the supplier company name

The supplier-portal route resolves the supplier via
`User.email == Supplier.contact_email`. The seed creates matching
emails for every demo supplier (`supplier1@avsglobal.com` ↔ the
Rotterdam supplier, etc.), so login is just
`supplier2@avsglobal.com` / `demo123`. If you re-seed and a
supplier's `contact_email` drifts from the matching User's email,
the login returns 403 with the detail
`"No supplier profile bound to this user account"`.

### Marketplace flow: ask-clarification puts the order in limbo

After `POST /orders/{id}/clarify` the order status is
`awaiting_clarification` and the supplier portal will *not* show
the RFQ until the purchaser answers (`POST /orders/{id}/clarify/answer`).
The thread is append-only; both sides see the same view.

---

## Permissions & sealed bids

The same platform serves six role archetypes and they see the
world differently. The RBAC shape is real — the API enforces it
on every protected route — and the frontend additionally gates
its UI on the caller's roles and permissions.

### Who sees what

| Role | Marketplace sim | RFQ compare | Vessel scope |
|------|----------------|-------------|--------------|
| `super_admin` | Full leaderboard (names, prices, ratings, subscores) | Full results | All vessels |
| `fleet_admin` | Same as `super_admin` | Same as `super_admin` | Their fleet |
| `purchasing_officer` | **Sealed-bid** view (ranked "Bidder 1, Bidder 2, …", winner's total + lead time + score only) | "Re-rank bids (sealed)" — same endpoint, redacted response | Their vessel |
| `vessel_captain` | Sealed view | Sealed view | Their vessel |
| `chief_steward` | No access (no `rfq:simulate:own`) | No access (no `quotes:compare:own`) | Their vessel |
| `supplier` | Their own bids + counter-offer terms they received (portal not shipped yet) | Their inbox | External |

### Sealed bids

A `purchasing_officer` running `POST /rfq/{id}/compare` or
`POST /rfq/{id}/simulate` gets back a redacted shape:

```json
{
  "results": [
    { "rank": 1, "label": "Bidder 1", "total": 4250.00, "lead_time_days": 5,    "score": 0.91 },
    { "rank": 2, "label": "Bidder 2", "total": null,    "lead_time_days": null, "score": 0.84 },
    { "rank": 3, "label": "Bidder 3", "total": null,    "lead_time_days": null, "score": 0.77 }
  ],
  "winner_rank": 1
}
```

The DB still holds the truth (supplier names, prices, ratings);
the redaction happens at the API boundary in
`backend/app/services/rfq_serializers.py`. Admin and fleet_admin
see the full unsealed shape; everyone else gets the sealed view.
A single RFQ can be viewed sealed by a purchaser and unsealed by
an admin in the same session.

Why response-side filtering, not a `sealed_bid_mode` flag on the
RFQ itself? Because the data model doesn't need to know. The
audit log, the counter-offer workflow, and the eventual supplier
portal all need the real numbers regardless of who is asking.
Filtering at the boundary is simpler and harder to bypass.

### Counter-offer classification

Counter-offer terms (target prices, lead-time squeeze) are
classified procurement information. The engine tags the
resulting `market_sim_events` row with
`visibility=winner_only` and
`visible_to_supplier_ids=[winner_supplier_id]`. The response
serializer turns that into a redacted "Counter-offer sent to
winner" stub for non-admin, non-winner callers.

The rule is ready for the supplier portal even though the
portal itself doesn't ship in this iteration — the moment a
supplier endpoint queries the event log, the rule is already
in place.

### The `/permissions` page

Visible to every authenticated user in the sidebar. Renders:

- **You** — your roles, vessel scope, JWT subject.
- **Your permissions** — every `resource:action:scope` string in
  your token, grouped by resource.
- **Role × permission matrix** (admin only) — every role from
  `SYSTEM_ROLES` × every permission from `SYSTEM_PERMISSIONS`,
  with green checks where the DB has a grant. Includes a
  "Copy as markdown" button for the slide handout.
- **Sealed-bid explainer** — what non-admin callers see vs.
  what admins see, and why.

### Vessel scoping

A purchaser on vessel 0 gets 404 on RFQs / orders belonging to
vessel 1, 2, 3, or 4 — not 403, so we don't leak resource
existence across vessels. The check is
`assert_vessel_access(token, vessel_id)` in
`backend/app/deps/auth.py`. Admins and fleet_admins always pass
(they own the fleet). External users with `vessel_id=null`
(suppliers) are denied unless they have an admin role.

The deep-dive lives in
[`docs/architecture/08-rbac-and-sealed-bidding.md`](./docs/architecture/08-rbac-and-sealed-bidding.md).

---

## Notifications

A per-user inbox backed by the `notifications` table. Each row has a
`type` discriminator, a `title`, an optional `body`, an optional JSONB
`data` payload (used by the frontend for deeplinks + icons), and a
nullable `read_at` (NULL = unread).

**Server side** — `app/services/notifications.py` exposes two helpers:

- `create_notification(db, *, user_id, type, title, body, data)` — insert one. Every call also creates a duplicate for all `super_admin` users with `[Admin]` title prefix (`select(UserRole.user_id).join(Role)...where Role.name == 'super_admin'`).
- `notify_order_transition(db, order, old_status, *, actor_id=None)` —
  the most common call site. Called from `POST /api/v1/orders/{id}/transition`
  whenever an order's status changes. The recipient is `order.assigned_to`
  (falling back to `order.created_by`); the actor who triggered the
  transition is not notified (avoids self-spam).

Adding a new trigger: write to the same table from your service code.
The model accepts `type` values of `order_transition`, `rfq_awarded`, or
`system` today — extend `NotificationType` to add more.

**Client side** — `frontend/src/components/NotificationsPanel.jsx` is the
bell dropdown. The badge in the header is driven by a 30 s polling loop
on `GET /notifications/unread-count` (so the network round-trip is
tiny — just an integer). The full list is fetched only when the panel
opens. Mark-read and mark-all-read are individual PATCH calls.

---

## Troubleshooting

### Frontend shows "Not Found" on login

The Vite dev proxy is rewriting `/api` away. Open
`frontend/vite.config.js` and make sure the proxy entry does **not**
strip the prefix:

```js
proxy: {
  '/api': { target: 'http://localhost:8000', changeOrigin: true }
}
```

If a `rewrite: (path) => path.replace(/^\/api/, '')` line is present,
remove it. (The backend serves `/api/v1/...`; the proxy must pass the
path through unchanged.)

### `role "readonly" does not exist` on first boot

`app/db/session.py` creates a separate `read_engine` for production
that connects as a `readonly` role. In `local` and `development`
environments we skip creating it, but if you override `ENVIRONMENT` to
`staging` or `production` locally, you'll need to create the role or
keep `ENVIRONMENT=development`. See `app/db/session.py`.

### `invalid input value for enum unitofmeasure: "pail"`

The seed references `UnitOfMeasure.PAIL` but the original
`0001_initial` migration creates the Postgres enum without that
variant. Run this once after `alembic upgrade head` and **before**
`python -m scripts.seed`:

```sql
ALTER TYPE unitofmeasure ADD VALUE IF NOT EXISTS 'pail';
```

If the seed has already failed, re-run it after the `ALTER TYPE` —
the seeder is idempotent with `--skip-if-populated`.

### Unicode banner crashes the seed on Windows

Run the seed and uvicorn with UTF-8 mode so the `→` and `✅` characters
in the print statements don't trip the cp1254 console codec:

```powershell
$env:PYTHONUTF8 = 1
python -m scripts.seed
```

### `greenlet_spawn has not been called` / `MissingGreenlet`

An async route is dereferencing a relationship after the session has
been closed, or after the request has returned. Eager-load the
relationship with `selectinload(...)` in the query, or add
`lazy="selectin"` on the model relationship.

> The most common form in the marketplace flow was the supplier
> portal's list endpoint iterating `r.quotes` without a matching
> `selectinload(RFQ.quotes)`. The fix is at
> `backend/app/api/v1/supplier_portal.py:144` and the regression
> test is `tests/api/test_marketplace_bugfixes.py::TestSupplierPortalListEagerLoads`.

### `invalid input value for enum auditaction: "..."`

The `AuditAction` enum binds its *value* (lowercase) to the PG enum,
not the *name* (uppercase). The PG enum was extended by migration
`0008_auditaction_values` to include the lowercase counterparts of
the original 16 audit values, so every existing `AuditLog` write
binds successfully. If you see this error, either the migration
didn't apply (run `alembic upgrade head`) or a new enum member
was added without extending the PG enum.

### `no rows for one()` / `multiple rows for scalar_one()`

Most common in the marketplace test suite when a fake session
returns an empty list where the route expects a single row. The
fix is to make the fake return a single row in `_FakeResult` (or
add an extra payload to the `rows_per_call` list) so the route
sees the same shape it would in production.

### Backend starts but every API call returns 500 with the same traceback

Almost always a lazy-load after the session closes. Look for the route
that reads `obj.related` and either:
- add `.options(selectinload(Cls.related))` to the query, or
- read the related field inside the route (where the session is still
  open) and copy the value into a dict/response DTO.

### `pytest` is not recognized as a cmdlet

You haven't activated the virtual environment. PowerShell's `PATH`
does not include `.venv\Scripts\` until activation. Either:

```powershell
cd backend
.venv\Scripts\Activate.ps1
pytest
```

…or call the in-venv `pytest.exe` directly without activating:

```powershell
cd backend
.\.venv\Scripts\pytest.exe
```

If activation fails with `running scripts is disabled on this
system`, run PowerShell **as Administrator** once and set the
execution policy for your user:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

Then close and reopen the shell.

### Sim can't reach the backend (`ConnectionError`)

If you're running the sim **locally** (not via Docker), it defaults
to `http://localhost:8000` — which assumes the backend is also
running on the host. If the backend is in a different container or
on a different host, pass `--backend-url` or set `SIM_BACKEND_URL`.

If you're running the sim via **docker-compose**, it points at
`http://backend:8000` (the service name) and waits for the
`backend: service_healthy` condition. If the sim exits immediately
with a connection error, check `docker logs avs-backend` — the
backend's `/health` endpoint must return 200 for the sim to start.

### Sim ingests are rejected with `400 Bad Request`

The most common cause is a stale `mmsi` field. The DB enforces
`mmsi ~ '^[0-9]{9}$'`; if any scenario produces a non-9-digit
value, the entire batch is rejected. Run `python -m sim.runner
--dry-run --max-iterations 3` to log the batch contents before
they hit the network.

### Sim is running but the Fleet Map shows no movement

Two things can cause this; check them in order.

1. **You started `suez_blockage`.** That scenario sets
   `port_dwell_minutes=10_000_000` globally on the world config, so
   every vessel sits at berth for ~19 years of sim time. See the
   [AIS simulator](#ais-simulator) section for the full explanation.
   Switch to `default_med` if you want to see polylines forming.

2. **You started `default_med` but the markers still aren't moving.**
   The map polls `/api/v1/internal/ais/positions` every 5 s, so motion
   only *looks* smooth if a leg takes more than 5 wall-seconds. The
   default time scale (1 wall-second = 1 sim-second) is fine — a
   3-hour leg takes 3 wall-minutes, and the markers glide across
   the Med. If you raised `SIM_SIM_TIME_SCALE`, set it back to the
   default (omit the env var) for smooth animation, or accept that
   higher scales will look like "popping" between waypoints.

### Fleet Map loads but stays empty even though sim is running

The page polls `/api/v1/internal/ais/positions` every 5 s. If the
query param `event_type=position_report` is being dropped (e.g. by a
misconfigured Vite proxy), the response will only contain rows for
event types that *do* have lat/lon. Check the browser devtools
network tab — the URL should end with
`?scenario=…&event_type=position_report&limit=1000`.

If the page shows the "No position data yet" empty state but the
sim is running, check the scenario dropdown — it must match the
scenario the sim was started with (default is `default_med`). The
empty-state message names the selected scenario, so it should
self-diagnose.

### Vessel polylines cut through land on the Fleet Map

Pre-fix, the sim steered each vessel directly at the *destination*
on every tick, producing a piecewise-rhumb-line that crosses land
on long ocean legs (Trieste → Malta via the Italian peninsula, for
example). The current implementation in `sim/world.py::_handle_underway`
steers toward the *next unvisited waypoint* along the great-circle
polyline, advancing the waypoint index when the vessel crosses it
(distance < 0.5 nm, OR bearing to waypoint more than 90° off
bearing to destination). The result is a polyline that follows
the great-circle arc — through the East China Sea, around the
Italian boot, etc. — not a straight-line shortcut.

---

## Testing

### Backend (pytest)

The backend ships **427 tests** covering the synthetic AIS sim
(including the great-circle waypoint-following and wall-clock
timestamp regressions), the sealed-bid counter-offer
classification, the RBAC permission matrix, the IMPA-first
catalog reader, the marketplace redesign (proposal composer,
supplier gate, preparation sweeper, ETA snapshot), the
clarification thread, and the 3 marketplace-flow bugfixes
pinned in `test_marketplace_bugfixes.py`.

| Test file                                            | Count | Area                                                  |
| ---------------------------------------------------- | ----- | ----------------------------------------------------- |
| `tests/sim/test_types.py`                            | 12    | Frozen dataclasses (Port, Vessel, PositionReport…)    |
| `tests/sim/test_ports_and_vessels.py`                | 13    | Static fixtures (54 ports, 12 vessels, MID 9xx MMSIs) |
| `tests/sim/test_geo.py`                              | 31    | Pure math (Haversine, slerp, bearing)                 |
| `tests/sim/test_routes.py`                           | 13    | `build_route`, `build_circular_route`                 |
| `tests/sim/test_world.py`                            | 16    | `World.step()` tick loop, waypoint following, wall-clock `event_ts` |
| `tests/sim/test_events.py`                           | 14    | `EventBatch` JSON adapter (pydantic contract)         |
| `tests/sim/test_backend_client.py`                   | 3     | httpx client, retry policy, injected vs owned client  |
| `tests/sim/test_scenarios.py`                        | 38    | 4 built-in scenarios + registry + world integration   |
| `tests/sim/test_runner.py`                           | 20    | CLI: `parse_args`, `build_runtime`, `run_loop`, `main`|
| `tests/api/internal/test_ais_ingest.py`              | 10    | `/api/v1/internal/ais/ingest` end-to-end              |
| `tests/api/test_rbac.py`                             | 27    | Role × permission matrix; row-level vessel scoping   |
| `tests/api/test_rfq_eligible.py`                     | 9     | RFQ eligibility filter                                |
| `tests/api/test_counter_offer_visibility.py`         | 12    | Counter-offer terms classified `winner_only`         |
| `tests/api/test_impa_catalog.py`                     | 9     | `/catalog/impa` shape (defensive `Array.isArray` reader) |
| `tests/api/test_redaction.py`                        | 24    | Vessel label redaction (CRC32 → "Vessel #N")          |
| `tests/api/test_marketplace_bugfixes.py`            | 5     | 3 marketplace-flow bugfix regressions (Sept 2026)     |
| `tests/market_sim/test_market_sim.py`                | 7     | Legacy sealed-bid engine (kept for backward compat)   |
| `tests/market_sim/test_engine.py`                    | 17    | Market-sim engine internals (kept for backward compat)|
| `tests/market_sim/test_agent.py`                     | 13    | Market-sim bidding-agent heuristics                   |
| `tests/marketplace/test_clarification.py`            | 14    | Admin↔purchaser clarification thread                  |
| `tests/marketplace/test_compose_proposal.py`         | 3     | Per-line proposal composer                            |
| `tests/marketplace/test_eta_snapshot.py`             | 1     | ETA/ETD snapshot from the latest AIS report           |
| `tests/marketplace/test_preparation_timeout.py`      | (TestClass) | 24h preparation sweeper drops slow suppliers    |
| `tests/marketplace/test_purchaser_approval.py`       | 6     | Purchaser approval flow                               |
| `tests/marketplace/test_rfqs_for_compose.py`         | 13    | `/marketplace/orders/{id}/rfqs-for-compose` candidate filter |
| `tests/marketplace/test_sealed_identities.py`        | 8     | Supplier identity stays sealed until approval         |
| `tests/marketplace/test_supplier_gate.py`            | (TestClass) | IMPA-first "can deliver in window" gate            |
| `tests/marketplace/test_supplier_portal.py`          | 16    | Supplier portal: list / detail / accept / assignments / lazy-load / awarded-form hides |
| **Total**                                            | **427** | Full suite runs in **~13 seconds**                 |

(The `427` number comes from `pytest --collect-only`; the lower
`def test_…` count you see from `grep` is because many tests live
inside `class Test…` blocks. Some `async def` test methods are
shown as `(TestClass)` in the table because pytest renders them
as `<Coroutine>` in `--collect-only` and a strict function count
skips them — the totals still sum to 427.)

**macOS / Linux**
```bash
cd backend
source .venv/bin/activate
pytest                       # run all 427 tests
pytest -k search            # only tests whose name matches "search"
pytest --cov=app             # with coverage report
pytest -k "ingest or sim"    # run two slices at once
```

**Windows (PowerShell)**
```powershell
cd backend
.venv\Scripts\Activate.ps1
pytest                       # run all 427 tests
pytest -k search            # only tests whose name matches "search"
pytest --cov=app             # with coverage report
```

If you can't activate the venv (or don't want to), call the
in-venv `pytest.exe` directly:

```powershell
# Windows — bypasses activation
.\.venv\Scripts\pytest.exe
```

> **PowerShell execution policy:** if `.venv\Scripts\Activate.ps1`
> fails with `running scripts is disabled on this system`, run
> PowerShell **as Administrator** once:
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
> ```
> Then close and reopen the shell.

`pyproject.toml` configures pytest with `asyncio_mode = "auto"`, so
async tests don't need a `@pytest.mark.asyncio` decorator.

### Lint and types (backend)

The dev extras install `ruff` and `mypy`:

```bash
cd backend
ruff check app sim tests             # lint (rules: E, F, I, N, W, UP, B, C4, ANN, SIM, PIE, T20, TD, PTH, ERA, RET, ICN, ARG)
ruff format app sim tests            # autoformat
mypy app                             # type-check (strict_optional = true)
```

### Frontend

The frontend has **no test suite wired up yet** — no vitest config,
no test files, no Playwright. `package.json` exposes only
`dev`, `build`, `preview`, and `lint`:

```bash
cd frontend
npm install
npm run lint                 # oxlint (only available frontend check)
```

The `npm run test` and `npm run test:e2e` commands you might
expect to work are **not defined yet** — the snippets below are
forward-looking and will not run today:

```bash
npm run test                 # vitest unit tests (not yet wired)
npm run test:e2e             # playwright end-to-end (not yet wired)
```

---

## Production checklist

Before you ship this anywhere, do these things:

- [ ] Replace `JWT_*_KEY_PATH` with a real key pair from your secrets manager
- [ ] Change all demo passwords (`admin`, `captain`, …)
- [ ] Set `ENVIRONMENT=production` and `LOG_LEVEL=WARNING`
- [ ] Point `DATABASE_URL` at a managed Postgres (RDS, Cloud SQL, Aurora)
- [ ] Front the API with a real WAF (Cloudflare, AWS WAF) and IPsec/SSL VPN
- [ ] Replace in-memory IDS counters with Redis-backed (we already wired
      the env var, just need the connection)
- [ ] Configure Prometheus to scrape `/metrics` and pipe security events
      into your SIEM
- [ ] Set up read-replica connection string for `READ_REPLICA_URL`
- [ ] Configure CORS to your real frontend origin
- [ ] Either remove the `app/api/v1/internal/` router or front it with
      a private-network firewall; the AIS ingest endpoints are
      unauthenticated
- [ ] Enable Postgres `pg_stat_statements` and tune `work_mem`
- [ ] Run a load test with `locust` or `k6` against the catalog endpoint
- [ ] Set up PWA hosting on HTTPS (Service Workers require it)
- [ ] Set up CI to run `pytest` and `ruff check` on every push
- [ ] Replace the in-app per-user `notifications` table polling with
      a WebSocket / SSE channel when your traffic profile demands it
      (the current 30 s polling is fine for thousands of users, not millions)

---

## Contributor notes

A couple of conventions this project follows that aren't obvious
from the code alone.

### Two readmes, two audiences

This folder's `readme.md` is the **GitHub-visitor** version:
polished, badge row, marketing-flavored highlights, demo accounts
spelled out. The internal development copy lives one folder up at
`mock-up-backup/readme.md` and has a more personal tone (demo-day
reminders, "what tripped me up" notes, internal context).

They are **not** mirrors of each other. The backup folder is the
active dev workspace; this folder is what gets pushed to GitHub.
Content gets reviewed and selectively synced, not bulk-copied. The
project story lives in [`REPORT.md`](./REPORT.md) and only here.

### Demo seed lives in the backup folder, not here

`backend/scripts/seed.py` is the most-tweaked file in the project
— new demo products, supplier-account shuffles, AIS sim scenarios,
port data all land there first. The canonical version lives in
`mock-up-backup/backend/scripts/seed.py`. The version in this
folder is the 2026-09-03 snapshot; if you re-seed and find
something missing, check the backup folder for the latest.

The standalone `backend/scripts/seed_demo_accounts.py` (a small
helper for adding the 9 demo users on top of an existing seed)
**is** mirrored.

### How the marketplace simulator fits

The `sim/` package contains two distinct subsystems: the **AIS
simulator** (background process generating synthetic vessel traffic)
and the **marketplace simulator** (inline supplier-bid simulation
that runs synchronously on `POST /api/v1/rfq/{id}/simulate`). The
AIS sim is long-lived and tick-based; the marketplace sim is
request-scoped and completes in <2s. They share a directory
because the test scaffolding and CLI patterns are similar, not
because they share runtime architecture.

---

## Marketplace manual flow (no Docker)

Updated: 2026-09-14. Browser-only navigation path:
`/marketplace/send` → `/marketplace/markup/{rfq_id}` → `/marketplace/review/{rfq_id}`.

Key fixes applied today:
- `marketplace_simple.py`: `GET /marketplace/rfqs/{rfq_id}` returns `RFQDetailOut` with `items` (including `impa_code`) and `quotes`.
- `rfq.py`: fixed `compare_quotes` (`is_rejected` → `len(quotes)`).
- `MarketplaceMarkup.jsx`: added `import React` (fixed `React.Fragment` blank screen); `impa_code` shown in comparison table.
- `SupplierQuoteForm.jsx`: fixed `LineItemRow` key lookup (`rfq_item_id` → `item.id`) so submitted prices calculate correctly.
- `OrderDetail.jsx`: fixed RFQ card link (`/marketplace/markup/${r.id}`).

Known gotcha: supplier quote `unit_price` must be non-zero for the subtotal/total to calculate; empty price submits `USD 0`.

---

## License

MIT © 2026 AVS Global. See [`LICENSE`](./LICENSE).

For the project story, design rationale, and what's next, see
[`REPORT.md`](./REPORT.md).

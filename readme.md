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
![Tests: 199 passing](https://img.shields.io/badge/tests-199%20passing-brightgreen)

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
  scoring (weights tunable via env vars).
- **Customs & port regulation engine** — JSONLogic-lite evaluator over
  (order, country) → severity, blocking flag, permit requirement.
- **Per-user notifications** — server-side inbox + 30s polling badge +
  bell panel; triggered automatically on order state transitions.
- **Synthetic AIS traffic** — standalone `sim/` package decoupled
  from FastAPI/SQLAlchemy, with 4 built-in scenarios (Mediterranean
  shuttle, Suez blockage, North-Atlantic storm rerouting, quiet
  harbor). Same feed your production data pipeline would consume.
- **199 passing tests** — pytest with `asyncio_mode = "auto"`; the
  sim package has 195 unit tests, the AIS ingest endpoint has 4
  end-to-end tests.

## Quick links

- **[`REPORT.md`](./REPORT.md)** — the project story: motivation,
  what we built, what's not done, what we'd do next. Read this if
  you're evaluating the project.
- **[`docs/architecture/`](./docs/architecture/)** — six deep-dive
  documents on system topology, indexing, RBAC/security, offline-first,
  catering & RFQ, and the Figma design system.
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
8. [Demo flows](#demo-flows)
9. [Notifications](#notifications)
10. [Troubleshooting](#troubleshooting)
11. [Testing](#testing)
12. [Production checklist](#production-checklist)
13. [License](#license)

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
| **IDS/IPS** at the perimeter                      | Brute-force counter, port-scan detector, SQL/XSS injection filter, structured security events          |
| **Per-nationality catering plans**                | Voyage algorithm: calorie targets × crew × days + buffer, menu templates per (nationality, meal_type)  |
| **Supplier bidding** with weighted comparison     | RFQ → quotes → `compare_quotes` with price/lead-time/reliability/quality scores                        |
| **Customs & port regulation** filter              | JSONLogic-lite condition evaluator over (order, country) → severity, blocking flag, permit requirement |
| **Per-user notifications**                        | Server-side inbox + 30s polling badge, in-app bell panel, mark-read/mark-all-read                     |
| **Modern UI** designed in Figma                   | Component-based, dark mode, TanStack-Virtual data grids, design tokens mirrored from Figma             |
| **Live synthetic AIS traffic** on a map           | Standalone `sim/` package, 4 scenarios, polled at 5s by a Leaflet map page                             |

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
│   │   │   ├── catalog.py            #   /catalog/{products,categories,impa,issa,stats}
│   │   │   ├── catering.py           #   /catering/{menus,nationalities,provisioning-plans,…}
│   │   │   ├── customs.py            #   /customs/{countries,rules,port-regulations,evaluate}
│   │   │   ├── dashboard.py          #   /dashboard/{overview,recent-orders,…}
│   │   │   ├── notifications.py      #   /notifications (+ /unread-count, /{id}/read, /read-all)
│   │   │   ├── orders.py             #   /orders + /{id}/transition (fires notification on transition)
│   │   │   ├── ports.py              #   /ports (incl. /_/countries)
│   │   │   ├── rfq.py                #   /rfq/{for-order,quotes,compare}
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
│   │   │           └── 0002_ais_position_reports.py
│   │   └── __main__.py               # `python -m app` shim
│   ├── sim/                          # Synthetic AIS data simulator (standalone)
│   │   ├── types.py                  #   Port, Vessel, Route, PositionReport, SimEvent
│   │   ├── geo.py                    #   Haversine, slerp, initial-bearing math (pure)
│   │   ├── ports.py                  #   54 hand-picked maritime hubs
│   │   ├── vessels.py                #   15 fictional vessels (MID 9xx MMSIs)
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
│   │   ├── api/internal/test_ais_ingest.py   #   4 tests
│   │   └── sim/                              #   195 tests across 9 files
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
│   │   ├── pages/                    # 15 page-level components
│   │   │   ├── Login.jsx  Dashboard.jsx  Catalog.jsx  ProductDetail.jsx
│   │   │   ├── Orders.jsx  OrderCreate.jsx  OrderDetail.jsx
│   │   │   ├── RFQ.jsx  Catering.jsx  Customs.jsx
│   │   │   ├── Ports.jsx  Vessels.jsx  FleetMap.jsx
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
├── docs/architecture/                # 6 deep-dive docs
│   ├── 01-system-architecture.md     #   (196 lines) high-level topology
│   ├── 02-indexing.md                #   (159 lines) catalog FTS + indexes
│   ├── 03-rbac-security.md           #   (168 lines) auth + IDS/IPS
│   ├── 04-offline-first.md           #   (198 lines) IndexedDB + replay
│   ├── 05-catering-rfq.md            #   (173 lines) catering algorithm + RFQ scoring
│   └── 06-figma-design-system.md     #   (163 lines) design tokens
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

| Email                       | Username    | Password   | Role                 | Vessel |
| --------------------------- | ----------- | ---------- | -------------------- | ------ |
| `admin@avsglobal.com`       | `admin`     | `admin123` | `super_admin`        | —      |
| `captain@avsglobal.com`     | `captain`   | `demo123`  | `vessel_captain`     | 0      |
| `purchasing@avsglobal.com`  | `purchaser` | `demo123`  | `purchasing_officer` | 0      |
| `steward@avsglobal.com`     | `steward`   | `demo123`  | `chief_steward`      | 0      |
| `supplier@apcmarine.sg`     | `apcmarine` | `demo123`  | `supplier`           | —      |

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
| POST   | `/orders`                       | `order:create`  | Create order (runs customs evaluation)             |
| GET    | `/orders/{id}`                  | bearer          | Order with items + RFQ list                        |
| POST   | `/orders/{id}/transition`       | `order:write`   | Drive state machine (emits a `Notification` to the assignee — see [Notifications](#notifications)) |

### RFQ

| Method | Path                                  | Auth             | Purpose                                          |
| ------ | ------------------------------------- | ---------------- | ------------------------------------------------ |
| GET    | `/rfq`                                | bearer           | RFQ list                                         |
| POST   | `/rfq/for-order/{order_id}`           | `rfq:create`     | Build RFQ to suppliers at destination port       |
| GET    | `/rfq/{rfq_id}`                       | bearer           | RFQ detail with all quotes                       |
| POST   | `/rfq/quotes`                         | `quote:create`   | Supplier submits a quote                         |
| POST   | `/rfq/{rfq_id}/compare`               | `rfq:award`      | Weighted bid comparison                          |

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
| `sim.vessels`       | 15 fictional vessels (MID 9xx MMSIs)                                       |
| `sim.routes`        | `build_route`, `build_circular_route` — great-circle math                   |
| `sim.world`         | Tick loop. `World.step()` yields `(PositionReport, [SimEvent])` per vessel  |
| `sim.events`        | `EventBatch` — JSON adapter that produces the `IngestBatchIn` shape         |
| `sim.backend_client`| Async HTTP client (httpx) with retry policy + health check                 |
| `sim.config`        | `SimSettings` (pydantic-settings, `SIM_` env prefix)                        |
| `sim.scenarios`     | Frozen `Scenario` registry with `get_scenario(name)` lookup                 |
| `sim.runner`        | CLI entry point; drives the world, batches events, flushes to backend       |

The simulator's design and the rationale behind the
`source` column / no-FK isolation are documented in
`backend/app/models/ais.py` and `backend/app/api/v1/internal/ais.py`.

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
7. Click "Send RFQ to suppliers" → status = rfq_in_progress
8. (Log in as the order's assigned_to user) → bell badge increments
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

## Notifications

A per-user inbox backed by the `notifications` table. Each row has a
`type` discriminator, a `title`, an optional `body`, an optional JSONB
`data` payload (used by the frontend for deeplinks + icons), and a
nullable `read_at` (NULL = unread).

**Server side** — `app/services/notifications.py` exposes two helpers:

- `create_notification(db, *, user_id, type, title, body, data)` — insert one
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

---

## Testing

### Backend (pytest)

The backend ships **199 tests** covering:

| Test file                                | Count | Area                                                  |
| ---------------------------------------- | ----- | ----------------------------------------------------- |
| `tests/sim/test_types.py`                | 12    | Frozen dataclasses (Port, Vessel, PositionReport…)    |
| `tests/sim/test_ports_and_vessels.py`    | 13    | Static fixtures (54 ports, 15 vessels)                |
| `tests/sim/test_geo.py`                  | 31    | Pure math (Haversine, slerp, bearing)                 |
| `tests/sim/test_routes.py`               | 13    | `build_route`, `build_circular_route`                 |
| `tests/sim/test_world.py`                | 14    | `World.step()` tick loop, port events                 |
| `tests/sim/test_events.py`               | 14    | `EventBatch` JSON adapter (pydantic contract)         |
| `tests/sim/test_backend_client.py`       | 25    | httpx client, retry policy, injected vs owned client  |
| `tests/sim/test_scenarios.py`            | 37    | 4 built-in scenarios + registry + world integration   |
| `tests/sim/test_runner.py`               | 30    | CLI: `parse_args`, `build_runtime`, `run_loop`, `main`|
| `tests/api/internal/test_ais_ingest.py`  | 4     | `/api/v1/internal/ais/ingest` end-to-end              |
| **Total**                                | **199** | Full suite runs in **~5 seconds**                  |

(The `199` number comes from `pytest --collect-only`; the lower
`def test_…` count you see from `grep` is because many tests live
inside `class Test…` blocks.)

**macOS / Linux**
```bash
cd backend
source .venv/bin/activate
pytest                       # run all 199 tests
pytest -k search            # only tests whose name matches "search"
pytest --cov=app             # with coverage report
pytest -k "ingest or sim"    # run two slices at once
```

**Windows (PowerShell)**
```powershell
cd backend
.venv\Scripts\Activate.ps1
pytest                       # run all 199 tests
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

## License

MIT © 2026 AVS Global. See [`LICENSE`](./LICENSE).

For the project story, design rationale, and what's next, see
[`REPORT.md`](./REPORT.md).

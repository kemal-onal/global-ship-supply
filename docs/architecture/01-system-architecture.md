# AVS Global — System Architecture

> Maritime ship supply and logistics operations platform.
> Built for AVS Global, a worldwide ship chandler serving container
> vessels, tankers, and bulk carriers.

---

## 1. Mission-critical use cases

| User             | What they do                                    | Why it matters                                |
| ---------------- | ----------------------------------------------- | --------------------------------------------- |
| Captain          | Review pending order, approve urgent request    | Avoids port-of-call stockouts                 |
| Chief steward    | Build catering order, plan voyage provisioning  | Crew welfare, regulatory calorie compliance   |
| Purchaser        | Run RFQs to suppliers at destination port       | Cost optimization, lead-time minimization     |
| Port agent       | View regulations, customs checklist             | Permit acquisition, port clearance           |
| Supplier         | Receive RFQ invitation, submit quote           | Win business, manage lead-times              |

---

## 2. High-level topology

```
                           ┌─────────────────────────┐
                           │   Browser / PWA client  │
                           │ (Vite + React + IndexedDB)│
                           └────────────┬────────────┘
                                        │ HTTPS / WSS
                                        │ (JWT in Authorization header)
                                        ▼
            ┌────────────────────────────────────────────────┐
            │                FastAPI gateway                  │
            │  ┌──────────────────────────────────────────┐  │
            │  │ SecurityMiddleware                        │  │
            │  │  - request-id                             │  │
            │  │  - rate limit (slowapi)                   │  │
            │  │  - port-scan detector (sliding window)    │  │
            │  │  - SQL/XSS injection filter (regex)       │  │
            │  │  - brute-force counter                    │  │
            │  └──────────────────────────────────────────┘  │
            │                                                │
            │  ┌──────────────────────────────────────────┐  │
            │  │ Routers                                    │  │
            │  │  /auth   /catalog  /orders  /rfq          │  │
            │  │  /catering  /customs  /sync   /dashboard  │  │
            │  │  /vessels  /ports    /users              │  │
            │  └──────────────────────────────────────────┘  │
            └────────────────┬────────────────────┬───────────┘
                             │                    │
                             ▼                    ▼
                ┌────────────────────┐   ┌──────────────────┐
                │   PostgreSQL 16    │   │  Redis 7         │
                │  (asyncpg driver)  │   │  (rate counters, │
                │                    │   │   session cache) │
                └────────────────────┘   └──────────────────┘
```

---

## 3. Module map (backend)

| Module       | Path                              | Purpose                                                                 |
| ------------ | --------------------------------- | ----------------------------------------------------------------------- |
| `core`       | `backend/app/core/`               | Settings, security, IDS/IPS state, structured logging                   |
| `db`         | `backend/app/db/`                 | SQLAlchemy Base, async session, naming convention, mixins               |
| `models`     | `backend/app/models/`             | SQLAlchemy ORM models (user, port, vessel, product, order, supplier…)   |
| `schemas`    | `backend/app/schemas/`            | Pydantic v2 request/response DTOs                                        |
| `services`   | `backend/app/services/`           | Business logic (search, catering, RFQ, customs, sync)                    |
| `api`        | `backend/app/api/v1/`             | FastAPI routers, dependency wiring                                       |
| `migrations` | `backend/app/db/migrations/`      | Alembic                                                                   |

---

## 4. Why each technology

| Layer            | Choice                | Why                                                                                                |
| ---------------- | --------------------- | -------------------------------------------------------------------------------------------------- |
| API framework    | FastAPI               | Async-native, Pydantic integration, OpenAPI out of the box                                         |
| ORM              | SQLAlchemy 2 (async)  | Mature ecosystem, async support, expression-based queries                                          |
| Database         | PostgreSQL 16         | FTS via `tsvector`, GIN indexes, partial indexes, JSONB, generated columns                         |
| Driver           | asyncpg               | Fastest async PostgreSQL driver in Python; transparent prepared statement cache                    |
| Migrations       | Alembic               | Standard tooling, async support via `async_engine_from_config`                                     |
| Cache / IDS      | Redis 7               | Backing store for sliding-window counters, IP reputation, distributed rate limit                  |
| Auth             | JWT RS256             | Asymmetric — the API can verify without holding the signing key                                    |
| Frontend         | React 19 + Vite 6     | PWA-friendly, fast HMR, native ESM                                                                 |
| Styling          | Tailwind v4           | Utility classes, design tokens, dark mode via CSS variables                                        |
| State            | Zustand               | Tiny, no boilerplate, persisted via middleware                                                     |
| Data fetching    | TanStack Query        | Cache, retry, optimistic updates, request dedup                                                    |
| Tables           | TanStack Virtual      | 100k-row capable, fixed/variable height, headless                                                  |
| Offline          | IndexedDB (idb)       | Stores catalog cache, order queue, device-id; sync engine drains queue on reconnect               |
| Service Worker   | Vite PWA plugin       | NetworkFirst for /api, CacheFirst for assets, auto-update registration                              |

---

## 5. Database architecture

### 5.1 Naming convention

All constraint names are deterministic so migrations are diff-friendly:

```python
NamingConvention(
  ix="ix_%(table_name)s_%(column_0_label)s",
  uq="uq_%(table_name)s_%(column_0_name)s",
  ck="ck_%(table_name)s_%(constraint_name)s",
  fk="fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
  pk="pk_%(table_name)s",
)
```

### 5.2 Core tables

- `users`, `roles`, `permissions`, `user_roles`, `role_permissions` — RBAC
- `countries`, `ports`, `port_regulations`, `customs_rules` — geography
- `vessel_types`, `vessels`, `vessel_specifications` — fleet
- `product_categories`, `products`, `product_specifications`, `product_suppliers` — catalog
- `impa_codes`, `issa_codes` — maritime standard code cross-references
- `suppliers`, `supplier_ports`, `supplier_ratings` — supplier master
- `orders`, `order_items` — order header & lines
- `rfqs`, `rfq_items`, `supplier_quotes`, `quote_items`, `bid_comparisons` — bidding
- `crew_nationalities`, `menu_templates`, `menu_items`, `provisioning_plans`, … — catering
- `sync_queue`, `sync_conflicts`, `offline_actions`, `device_registrations` — offline-first
- `audit_logs`, `security_events` — append-only observability

### 5.3 Indexing strategy

See `02-indexing.md` for the full B+tree / GIN / partial index discussion.

### 5.4 Read replica

`Settings.read_replica_url` allows pointing SELECT-heavy endpoints
(`/catalog`, `/dashboard`) at a hot-standby in production. The router
uses `Depends(get_read_session)` to opt in.

---

## 6. Request lifecycle

1. Browser sends `POST /api/v1/orders` with `Authorization: Bearer <jwt>`
2. Nginx → FastAPI via uvicorn (4 workers, async event loop)
3. `SecurityMiddleware`:
   - assigns a request id (X-Request-Id)
   - increments per-IP rate counter in Redis
   - scans path/query/body for injection regexes → 400 if match
4. SlowAPI rate limiter (per-IP, per-route)
5. Router dependency `get_current_user` validates JWT, hydrates User, enforces scopes
6. Pydantic validates body → service layer
7. Service layer:
   - calls `evaluate_order` (customs rule engine)
   - if no blocking issues, persists `Order` + `OrderItem` rows in a transaction
   - audit log row written
8. Response serialized by Pydantic v2 → JSON
9. Prometheus metrics increment (`http_requests_total`, latency histogram)

---

## 7. Why two databases, sometimes

- **Write path** (`DATABASE_URL`, asyncpg) — orders, RFQs, audit
- **Read path** (`READ_REPLICA_URL`, when set) — catalog browse, dashboard

PostgreSQL streaming replication handles the propagation. In dev we just point
both at the same instance.

---

## 8. Failure modes & mitigations

| Failure                                | Mitigation                                                              |
| -------------------------------------- | ----------------------------------------------------------------------- |
| VSAT drop mid-order                    | Action enqueued in IndexedDB, replayed on `online` event                |
| Two captains edit same order offline   | Server detects `updated_at > client_timestamp`, surfaces as conflict    |
| Supplier double-quote                  | Idempotency key (`client_action_id`) on the replay batch                |
| DB connection storm                    | asyncpg pool with `pool_size=20, max_overflow=10`, health-checked       |
| Brute-force on `/auth/login`           | 5 fails / 5 min → 429 for 15 min, security event logged                 |
| Massive result set in `/catalog`       | Strict `limit` ≤ 200, keyset pagination preferred for very deep paging  |
| FTS misconfiguration                   | Three independent tsvector columns let you re-index one without redoing all |

---

## 9. Observability

- `structlog` JSON logs with `request_id`, `user_id`, `path`
- Prometheus `/metrics` (default `uvicorn` metrics + custom counters)
- `audit_logs` table is append-only; `security_events` records every blocked attempt
- `GET /api/v1/dashboard/kpis` powers the home-page widgets

---

## 10. Future extensions (out of scope for MVP)

- WebSocket channel for live RFQ bid updates
- WebAuthn / FIDO2 for captain phone sign-in
- Read-write split with PgBouncer + HAProxy
- Migration of cache layer to Redis Cluster
- Event-sourced audit using a dedicated write-only schema

# Offline-first ordering (VSAT-resilient)

> **The problem**: A ship at sea uses VSAT satellite internet. The
> connection drops for 5–60 seconds every time the antenna realigns,
> and for hours at a time in storms or near coastlines. The crew must
> still be able to build and submit supply orders.
>
> **The solution**: A local IndexedDB store + Service Worker + a
> replay engine that drains the queue when connectivity returns.

---

## 1. Data flow

```
                    ┌──────────────────────────────────────────────┐
                    │  Captain builds cart while offline           │
                    │  (Vite + React + IndexedDB)                  │
                    └─────────────┬────────────────────────────────┘
                                  │   on submit
                                  ▼
                    ┌──────────────────────────────────────────────┐
                    │  order_queue  (IndexedDB)                    │
                    │  { client_action_id, resource, payload,     │
                    │    created_at, status: pending }             │
                    └─────────────┬────────────────────────────────┘
                                  │   navigator.onLine === true
                                  │   (online event / 30s tick)
                                  ▼
                    ┌──────────────────────────────────────────────┐
                    │  POST /api/v1/sync/replay                    │
                    │  { device_id, actions: [ ... ] }              │
                    └─────────────┬────────────────────────────────┘
                                  │
                                  ▼
                    ┌──────────────────────────────────────────────┐
                    │  Backend: per-action executor                │
                    │  - check updated_at vs client_timestamp      │
                    │    → conflict if server moved                 │
                    │  - apply mutation in a transaction           │
                    │  - return per-action result                  │
                    └─────────────┬────────────────────────────────┘
                                  │
                                  ▼
                    ┌──────────────────────────────────────────────┐
                    │  Client removes succeeded actions,           │
                    │  keeps failed ones for next retry            │
                    └──────────────────────────────────────────────┘
```

---

## 2. IndexedDB schema (versioned)

```ts
// db.js
catalog_cache:  keyPath: 'id', indexes: [category, sku]
carts:           keyPath: 'id'
order_queue:     keyPath: 'client_action_id', indexes: [created_at, status]
sync_meta:       keyPath: 'key'
```

Versioning:

- DB name: `avs-offline`
- Version 1: the four stores above
- Bump to v2 for additive changes; v3+ for breaking changes (with
  migration code in the `upgrade` callback)

---

## 3. Sync engine

Located at `frontend/src/offline/sync.js`. Entry points:

- `startSyncEngine()` — call once at app boot
- `drainQueue()` — POST up to 25 actions per batch
- `enqueueAction({ resource, action, payload })` — call from anywhere

Trigger conditions:

- App startup (after 2s grace)
- `window.addEventListener('online', …)`
- Every 30s when `navigator.onLine` is true
- Manually from the Sync page

Failure handling:

- Per-batch try/catch: on error, the batch is marked `failed` and the
  loop breaks (the remaining actions wait for the next cycle).
- `client_action_id` is a UUID generated client-side; the server uses
  it to dedupe (so a retried batch doesn't create duplicate orders).

---

## 4. Conflict resolution

If the server's `updated_at` is newer than the client's
`client_timestamp`, the action is **not** applied. Instead:

```json
{
  "client_action_id": "orders-1700000000-abc123",
  "status": "conflict",
  "reason": "server_updated_after_client",
  "server": { ... current state ... }
}
```

The action is left in the queue with `status='conflict'`, and a row is
inserted in `sync_conflicts`. The UI surfaces these on `/sync` and lets
the user pick:

- **Server wins** — discard the offline change
- **Client wins** — replay with `force=true` (re-asserts the payload)
- **Manual merge** — open a side-by-side editor

---

## 5. Service Worker (PWA)

Configured via `vite-plugin-pwa`:

| Pattern                       | Strategy       | Cache TTL |
| ----------------------------- | -------------- | --------- |
| `/api/*`                      | NetworkFirst   | 24 h      |
| HTML documents                | NetworkFirst   | —         |
| CSS / JS / images / fonts     | CacheFirst     | 30 d      |

Why `NetworkFirst` for API:

- Captain needs fresh regulatory data
- But if VSAT is down, the cached list keeps the catalog browsable
- 3-second network timeout → falls back to cache automatically

Service worker file is served with `Cache-Control: no-store` so updates
take effect immediately.

---

## 6. What we cache vs what we always fetch

| Resource              | Cached?         | Why                                        |
| --------------------- | --------------- | ------------------------------------------ |
| Catalog (last 500)    | yes, on browse  | Captain can browse offline                 |
| Order history         | no              | Authoritative server-side, conflicts costly|
| RFQ status            | no              | Bid timing is critical                     |
| Vessel / port master  | no (small)      | One-shot fetch on login                    |
| Regulations           | no (small)      | One-shot fetch on login, signed for safety |
| User profile          | no              | Always trust the server's view             |

---

## 7. Idempotency

`client_action_id` is the only piece of state the server stores to
deduplicate. Generated as:

```
<resource>-<unix_ms>-<random_6_char>
```

Stored in:

- `offline_actions.client_action_id` (unique index)
- `sync_queue.client_action_id`
- Returned in the response so the client can correlate

This means: even if the captain's packet is re-sent due to a flaky
uplink, the server applies the change exactly once.

---

## 8. Battery & bandwidth considerations

- The 30s polling interval is conservative; the actual trigger is the
  `online` event, which fires almost instantly when the link comes back
- VSAT bandwidth is precious; the catalog cache is capped at 500 items
  and pruned to the most recently viewed on each `cacheProducts` call
- Service worker only pre-caches assets declared in the manifest

---

## 9. Testing offline mode

```bash
# Chrome devtools → Network → Offline
# (or) Service Worker panel → "Offline" checkbox

# Submit an order while offline
# → toast: "Offline: order queued and will sync when VSAT returns"
# → order_queue store has 1 entry
# → flip back to Online
# → toast: order synced
```

The `Sync` page (`/sync`) shows the local queue depth, the server
queue, and any conflicts.

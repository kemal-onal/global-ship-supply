# Marketplace Simulator

> A **deterministic, in-request bid-war engine** that turns an open
> RFQ into a visible marketplace event. `SupplierAgent`s (one per
> eligible supplier) pick strategies, generate bids, the existing
> `compare_quotes` picks a winner, and a counter-offer triggers a
> round 2.

---

## 1. Why this exists

The department-head demo hinges on AVS as a **marketplace operator**,
not just a portal. The story is: "We don't just send your RFQ to
ten suppliers and wait. We run the marketplace — bids come in, you
see the war, you steer it with weights, you push back with a
counter-offer." This engine makes that story real and repeatable.

### 1.1 Goals (and what was deliberately not done)

| Goal                                                              | Status |
| ----------------------------------------------------------------- | ------ |
| One-click bid war, visible in the UI                               | ✅     |
| Round 2 via counter-offer (lead-time squeeze)                      | ✅     |
| What-if weight slider re-ranks without consuming the RFQ           | ✅     |
| Deterministic replays for the same seed + RFQ                     | ✅     |
| Reuses the production `compare_quotes` math (no shadow scorer)     | ✅     |
| Standalone `market_sim/` package + scenarios + CLI                | ❌ deferred — see §9 |
| Per-vessel counter-offer policy table                             | ❌ deferred |
| Long-running sim forks with their own state machine               | ❌ deferred |

The seam to upgrade to the heavy version is clean: `run_market_sim` is
a single async function. When the team wants background sims, extract
it into a `market_sim/` package with a runner — no rewrite.

---

## 2. The data model

### 2.1 `market_sim_events` table (migration 0003)

```sql
CREATE TABLE market_sim_events (
  id          UUID PRIMARY KEY,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  rfq_id      UUID NOT NULL REFERENCES rfqs(id) ON DELETE CASCADE,
  ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
  round       INTEGER NOT NULL DEFAULT 1,
  event_type  VARCHAR(40) NOT NULL,   -- run_start | bid_arrived | round_close | counter_offer | run_end
  supplier_id UUID NULL REFERENCES suppliers(id) ON DELETE SET NULL,
  payload     JSONB
);
CREATE INDEX ix_market_sim_events_rfq_ts ON market_sim_events (rfq_id, ts);
```

No enums on the table — stored as `VARCHAR(40)` and validated at the
application layer via `MarketSimEventType` (str, Enum). The schema
stays trivial and we don't fight Postgres enum evolution.

### 2.2 `rfqs.extra` JSONB

The RFQ *is* the run. No `market_sim_runs` header table. `rfqs.extra`
carries the live sim state:

```json
{
  "sim_round": 2,
  "last_sim_seed": 43,
  "last_sim_at": "2026-09-02T15:30:00Z"
}
```

### 2.3 Quotes (reused)

Sim quotes are **regular `supplier_quotes` rows** with `source="sim"`.
The existing `UniqueConstraint("rfq_id", "supplier_id")` means a real
supplier's manual quote pre-empts the sim for that supplier — the
engine filters those out at eligibility time.

> **Dry-run caveat:** in dry-run mode, the engine does **not** write
> any `supplier_quotes` rows. Scoring happens in memory in
> `_score_bids()` (a faithful re-implementation of `compare_quotes`'s
> math). This is the only way to re-simulate the same RFQ without
> hitting the unique constraint.

---

## 3. The engine

`backend/app/services/market_sim.py` is the whole engine in one
~250-line file. Three pieces:

### 3.1 `SupplierAgent` (in-memory dataclass)

```python
@dataclass
class SupplierAgent:
    supplier_id: UUID
    supplier_name: str
    rating_reliability: float
    rating_quality: float
    on_time_pct: float
    categories: list[str]
    base_unit_prices: dict[UUID, float]   # product_id → price, cached at run start
    base_lead_days: int
    rng_seed: int                          # hash((run_seed, supplier_id))
    strategy: Literal["aggressive", "balanced", "premium", "slow_but_cheap"]
```

Strategy is derived **once** at construction from the seeded supplier
ratings:

| Condition                                          | Strategy          |
| -------------------------------------------------- | ----------------- |
| `rating_overall >= 4.5 and on_time_pct >= 95`     | `premium`         |
| `on_time_pct < 88`                                 | `slow_but_cheap`  |
| `categories` hash is odd (deterministic 50/50)    | `aggressive`      |
| else                                               | `balanced`        |

The hash split is deliberate: it gives a stable mix of `aggressive`
and `balanced` agents across the seeded supplier pool without
needing an extra column on `suppliers`.

### 3.2 `Bid` (in-memory dataclass)

```python
@dataclass
class Bid:
    supplier_id: UUID
    line_items: list[dict]      # {product_id, quantity, unit_price}
    lead_time_days: int
    total: float
    strategy: str
    notes: str = ""             # visible in the timeline
```

`generate_bid()` per strategy (jitter seeded by
`(run_seed, supplier_id, round_n)` so replays are stable):

| Strategy         | Unit price                          | Lead time          |
| ---------------- | ----------------------------------- | ------------------ |
| `aggressive`     | `base * (1 - 0.10 + jitter)`        | `base_lead - 2`    |
| `balanced`       | `base * (1 - 0.05 + jitter)`        | `base_lead`        |
| `premium`        | `base * (1 + 0.08 + jitter)`        | `base_lead + 3`    |
| `slow_but_cheap` | `base * (1 - 0.18 + jitter)`        | `base_lead + 7`    |

`jitter = random.Random(seed).uniform(-0.02, 0.02)`.

Counter-offer terms cap the per-product price at the requested
`target_unit_price` (clamped to the agent's bid, never inflated).

### 3.3 `run_market_sim()` — the orchestrator

```python
async def run_market_sim(
    db, rfq, *,
    seed: int = 42,
    weights: dict | None = None,
    counter_offer_terms: dict | None = None,
    dry_run: bool = True,
) -> dict:
    # 1. Eligibility: active suppliers at rfq.port_id with no real
    #    supplier_quotes on this RFQ.
    # 2. If round 1, build one SupplierAgent per eligible supplier.
    # 3. If round 2, select in-contention agents (round-1 score
    #    within 0.05 of the winner) and rebuild from cached data.
    # 4. For each agent, call generate_bid() with round_n and
    #    counter_offer_terms; collect into bids[].
    # 5. dry_run: score in memory via _score_bids(); no DB writes.
    #    !dry_run: call submit_quote() per bid, then
    #    compare_quotes() with save=True.
    # 6. Persist market_sim_events for: run_start, each bid_arrived,
    #    counter_offer (if any), round_close, run_end.
    # 7. Return {round, winner, results, events, weights, dry_run}.
```

The 0.05 in-contention threshold was tuned against the seeded
supplier pool: 1–2 suppliers re-bid in round 2, enough to
demonstrate the round-2 mechanic without running the whole pool
again.

---

## 4. The endpoint

`POST /api/v1/rfq/{rfq_id}/simulate` in `backend/app/api/v1/rfq.py`.

```python
class SimulateIn(BaseModel):
    seed: int = Field(default=42, ge=0, le=2**31 - 1)
    weights: dict[str, float] | None = None
    counter_offer_terms: dict[str, Any] | None = None

@router.post("/{rfq_id}/simulate")
async def simulate_bidding(
    rfq_id: str,
    payload: SimulateIn,
    db: DBSession,
    token: CurrentToken,
    dry_run: bool = Query(default=True, description=…),
):
    if not token.has_permission("rfq:simulate:own"):
        raise HTTPException(403, "Missing permission: rfq:simulate:own")
    rfq = (await db.execute(
        select(RFQ).where(RFQ.id == rfq_id)
        .options(
            selectinload(RFQ.items),
            selectinload(RFQ.quotes).selectinload(SupplierQuote.supplier),
        )
    )).scalar_one_or_none()
    if not rfq: raise HTTPException(404, "RFQ not found")
    if rfq.status in (CANCELLED, EXPIRED):
        raise HTTPException(400, f"RFQ is {rfq.status.value}; cannot simulate bidding")
    result = await run_market_sim(db, rfq, ...)
    await db.commit()
    return result
```

**`selectinload` matters.** `run_market_sim` reads `rfq.items` and
`q.supplier` synchronously. Without eager loading, async SQLAlchemy
raises `MissingGreenlet: greenlet_spawn has not been called`.

### 4.1 Response shape

```json
{
  "round": 1,
  "winner": "9c9a3d3a-...-e1b0",
  "results": [
    {
      "supplier_id": "9c9a3d3a-...-e1b0",
      "supplier_name": "Maritime Provisions B.V.",
      "total": 329.93,
      "lead_time_days": 3,
      "reliability": 4.8,
      "quality": 4.7,
      "subscores": { "price": 0.82, "lead_time": 0.65, "reliability": 0.96, "quality": 0.94 },
      "score": 0.9168
    }
  ],
  "events": [
    { "id": "...", "ts": "2026-09-02T15:30:00Z", "round": 1,
      "event_type": "run_start", "supplier_id": null, "payload": {...} },
    ...
  ],
  "weights": { "price": 0.4, "lead_time": 0.2, "reliability": 0.2, "quality": 0.2 },
  "dry_run": true
}
```

---

## 5. Permissions

One new permission string: **`rfq:simulate:own`**. Granted to
`purchasing_officer` so vessel purchasers can run sims on their own
RFQs, and implicitly to `super_admin` via the catch-all.

Added in `backend/scripts/seed.py` as a separate `INSERT … ON
CONFLICT DO NOTHING`, so existing deployments pick it up on the
next `python -m scripts.seed` run without crashing.

---

## 6. The UI

`frontend/src/pages/MarketSim.jsx` — six sections.

### 6.1 Header

- **RFQ selector** — open + awarded RFQs only
- **"Run simulation" / "Re-run"** button — primary action
- **"Counter-offer"** button — enabled after first run, opens the modal
- **Status pills** — round, dry-run vs committed, winner chip

### 6.2 Bid-war timeline

Vertical list of `market_sim_events`. Each row:

- Color-coded round chip (round pill on the left, color from the
  supplier palette indexed by supplier)
- Event-type icon (Play, Gavel, Trophy, Hand, Sparkles)
- Strategy badge for `bid_arrived` events
- One-line excerpt (`$329.93 · 3d lead` for bids, `{"lead_days": 3}`
  for counter-offers)

### 6.3 Leaderboard + subscore bars

A 2-column grid:

- **Left**: table sorted by `score` desc. Columns: rank, supplier
  name (with crown icon for the winner), total, lead, score.
- **Right**: stacked horizontal `BarChart` from Recharts. Each row
  is a supplier, each stack is a subscore (price/lead-time/reliability/quality).

### 6.4 Why this winner

A horizontal bar chart with one bar per (weight × subscore)
contribution. The math is identical to the back-end's
`_score_bids()`:

```
contribution[k] = weights[k] * subscores[k]
total = Σ contribution[k] == quote.score
```

The user sees, for example: "Reliability contributed 0.19 to the
win — that's 40% of the score."

### 6.5 What-if sliders

Four range inputs (0.0–1.0) for the four weights. Σ display shows
the current sum (turns amber if it drifts from 1.0). The
"Re-rank with these weights" button calls the same sim endpoint
with the new weights — the engine re-uses the same seed and same
agent pool, so only the scoring changes.

### 6.6 Price × lead-time scatter

A `ScatterChart` with:

- **X** = quote total ($)
- **Y** = lead-time (days)
- **Bubble size** = reliability subscore × 100
- **Color** = purple for the winner, blue for the rest

### 6.7 Counter-offer modal

A simple modal with two fields:

- **New lead-time target** (days) — required for the demo
- **Price cap** (optional) — single-product, per-product caps
  would need a row per RFQ item; out of scope for the demo

On submit, sends `{counter_offer_terms: {lead_days: N}}` to the
sim endpoint, and round 2 re-bids the in-contention agents.

---

## 7. State machine — round 1 vs round 2

```
                    ┌────────────────────────────────────┐
                    │ RFQ in "open" status               │
                    │ POST /simulate (no terms)          │
                    └────────────────┬───────────────────┘
                                     │
                                     ▼
              ┌──────────────────────────────────────────┐
              │ Round 1                                  │
              │  - every eligible agent bids             │
              │  - scores computed                       │
              │  - winner = top by score                 │
              │  - 1 + N + 1 + 1 = (2+N) events logged   │
              └────────────────┬─────────────────────────┘
                               │
                               │ POST /simulate
                               │ { counter_offer_terms: {lead_days: 3} }
                               ▼
              ┌──────────────────────────────────────────┐
              │ Round 2                                  │
              │  - in-contention agents re-bid (≤ 0.05)  │
              │  - scores recomputed                     │
              │  - winner may change                     │
              │  - new events appended                   │
              └──────────────────────────────────────────┘
```

In both rounds the seed is `last_sim_seed + (round - 1)` so
re-running round 2 with the same terms gives the same bids.

---

## 8. Testing

### 8.1 Engine tests (30)

- `tests/market_sim/test_agent.py` — 13 tests. Strategy assignment,
  per-strategy bid math, jitter bounds, deterministic replay, price
  cap from counter-offer terms, lead-time floor.
- `tests/market_sim/test_engine.py` — 17 tests. Eligibility filter,
  round 1 + round 2 event counts, round-2 in-contention rule
  (0.05 threshold), event payload shapes, seed-from-payload helper,
  `STRATEGY_PARAMS` sanity, full run with 5 suppliers.
- **Total: 30 engine + agent + 7 route = 37 marketplace-sim tests.**

### 8.2 Route tests (7)

`tests/api/test_market_sim.py`:

- 401 without auth
- 403 without `rfq:simulate:own`
- 404 when RFQ missing
- 400 when RFQ is CANCELLED or EXPIRED
- 422 for `seed < 0` and `seed > 2**31`

### 8.3 Manual smoke

```bash
# Round 1
curl -X POST http://localhost:8000/api/v1/rfq/$RFQ/simulate \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}' | jq

# Round 2 with lead-time squeeze
curl -X POST http://localhost:8000/api/v1/rfq/$RFQ/simulate \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"counter_offer_terms": {"lead_days": 3}}' | jq
```

Round 1 should produce 2+N+2 events (run_start + N bid_arrived +
round_close + run_end) and round 2 only the in-contention
suppliers' bid_arrived.

---

## 9. What we're not doing (and why)

| Deferred                            | Why                                                                                              | Upgrade path                                       |
| ----------------------------------- | ------------------------------------------------------------------------------------------------ | -------------------------------------------------- |
| Standalone `market_sim/` package    | The engine runs once per request and returns in <2 s. No tick loop, no need for one.              | Extract `run_market_sim` into a `market_sim/` package with a runner |
| `market_sim_runs` header table      | The RFQ *is* the run. `rfq.extra` JSONB tracks sim state. One source of truth.                   | Add a `market_sim_runs` table when sims outgrow the RFQ lifecycle |
| Internal ingest + tick + batching   | Single-request sim doesn't need any of these                                                       | Add when sims become long-running                  |
| Per-vessel counter-offer policy     | Counter-offer terms live in the request payload today                                              | Add a `sim_policies` table when vessel-specific defaults become a thing |
| Frontend vitest setup               | Repo has no frontend test scripts; not in scope for this slice                                    | Separate work item                                 |
| Multi-tenant sim forks              | Out of scope for the single-vessel demo                                                            | Requires per-tenant `rfq.extra` and a runner       |

The seam is clean. Each deferred item is one table or one package
add, not a rewrite.

---

## 10. Operational notes

- **No background work.** The endpoint is synchronous; no queue, no
  worker. If a sim ever takes >2 s (100+ suppliers), revisit.
- **No idempotency key.** The sim is naturally idempotent under the
  same seed + RFQ; the response is reproducible. Re-running with a
  different seed is the same as running fresh.
- **Audit.** `market_sim_events` rows ARE the audit trail. The
  `rfq_awarded` notification still fires only in `dry_run=false`.
- **Replay.** The (rfq_id, seed) pair uniquely identifies a bid war.
  Storing the seed in `rfq.extra.last_sim_seed` makes it recoverable.

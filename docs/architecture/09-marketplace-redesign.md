# 09 — Marketplace redesign

> The sealed-bid auction is gone. The new flow is fan-out,
> per-line decisions, 24h supplier acceptance.

This doc describes the marketplace redesign: the new status model,
the new endpoints, the new services, the redaction invariants, and
the data model additions. It is the source of truth for the
`AWAITING_PURCHASER_APPROVAL` flow and the 24h preparation sweeper.

## Why we replaced the bid war

The old `MarketSimPage` was a sealed-bid auction: suppliers were
ranked by a weighted score, the winner was selected by the engine,
losing bids were sealed from the purchaser. The pitch was
"objective, defensible, fair to suppliers".

It was also opaque and slow. The lead time the engine returned was
based on simulated counter-offers, not on what the supplier could
actually fulfil. The "what-if" weight sliders were a demo toy, not a
real decision tool. And every bid war was the same shape — one
winner, full or nothing.

The new flow is a **fan-out, per-line decision, approval flow**:

1. The order is sent to every active supplier at the destination
   port.
2. Each supplier returns a per-line decision: **full / partial /
   none**, with a unit price if they're offering.
3. The company looks at the lattice of (line × supplier) and
   decides which fraction of which supplier's offer to use. They
   set a company margin.
4. The composed proposal goes to the purchaser with supplier
   identities sealed. They approve or reject.
5. On approval, each winning supplier gets a notification of their
   slice and has 24h to confirm they're preparing the goods. Slow
   ones are auto-dropped.

The pitch is now: "we can split a line across two suppliers, the
purchaser only sees the total, slow suppliers cost us money."

## Flow

```
PURCHASER                          COMPANY (admin only)                SUPPLIERS
─────────                          ─────────────────────                ─────────
1. POST /orders
   vessel, port, priority,
   lines: product_id (IMPA),
   description (intended use),
   quantity, notes
   → status: DRAFT

                                  2. POST /orders/{id}/clarify
                                     (loop: ask, answer, resolve)
                                     → status: QUOTING
                                  3. POST /orders/{id}/snapshot-eta
                                     (pulls AIS report)
                                  4. POST /rfq/for-order/{id}
                                     fans out to ALL active
                                     suppliers at the port
                                     → status: QUOTING
5. Each supplier opens
   /supplier, sees their
   invited RFQ.
                                  6. Each supplier POSTs their
                                     quote: per line full/partial/
                                     none + unit price
                                  7. Deadline (48h) OR
                                     all invited responded:
                                     → status: READY_FOR_COMPOSE

8. Admin opens /marketplace,
   sees the lattice
   (rows = lines, cols = suppliers).
                                  9. Admin POSTs /rfq/{id}/compose:
                                     for each line pick a supplier
                                     and use_full / use_half / drop.
                                     Set the company margin %.
                                     → status: AWAITING_PURCHASER_APPROVAL

10. Purchaser opens /orders/{id},
    sees the composed proposal
    (per-line total with margin,
    lead time, payment terms —
    supplier identity sealed).
    → Approve: status: CONFIRMED
       (each winning supplier
        notified, 24h window)
    → Reject: status: REJECTED + reason

                                  11. Each winning supplier
                                      opens /supplier, clicks
                                      "Accept my slice" within 24h
                                      → SupplierLineAssignment
                                         .confirmed_at = now

12. After 24h, admin sees a
    "preparation status" panel:
    confirmed (green) / unconfirmed (red, drop button)
    → Manual or auto drop flips
      SupplierLineAssignment.status = DROPPED
```

## Status model

```python
class OrderStatus(str, enum.Enum):
    DRAFT                       = "draft"
    AWAITING_CLARIFICATION      = "awaiting_clarification"   # NEW
    QUOTING                     = "quoting"                  # NEW
    READY_FOR_COMPOSE           = "ready_for_compose"        # NEW
    AWAITING_PURCHASER_APPROVAL = "awaiting_purchaser_approval"  # NEW
    CONFIRMED                   = "confirmed"
    IN_TRANSIT                  = "in_transit"
    DELIVERED                   = "delivered"
    COMPLETED                   = "completed"
    CANCELLED                   = "cancelled"
    REJECTED                    = "rejected"
```

The old `PENDING_APPROVAL`, `RFQ_IN_PROGRESS`, `BIDDING` values are
**deprecated but kept** in the enum so legacy data + tests don't
break. New code never sets them.

## Data model

### Migration `0005_marketplace_redesign.py`

New columns:

- `orders.company_margin_pct: Numeric(5,2)` default 8.00, nullable
- `orders.eta_at_port: DateTime(timezone=True)` nullable
- `orders.clarification: JSONB` nullable (list of
  `{id, question, answer, asked_by, answered_by, ts, resolved_at}`)
- `rfq_items.impa_code: String(20)` nullable (denormalized for the
  supplier portal — avoids a join to display)
- `supplier_quotes.decision_method: String(20)` nullable
  ("full" / "partial")
- `supplier_quotes.confirmed_at: DateTime(timezone=True)` nullable
- `supplier_quotes.preparation_deadline: DateTime(timezone=True)`
  nullable
- `quote_items.line_status: String(10)` default "full"
  ("full" / "partial" / "none")
- `quote_items.quoted_quantity: Integer` nullable (when partial,
  equals `ceil(requested/2)`; defaults to `quantity` when full)

New tables:

- `order_decisions` — `(id, order_id, rfq_item_id, supplier_id,
  quote_id, decision, unit_price, line_total, margin_pct,
  customer_facing_total, created_at, created_by)`
- `supplier_line_assignments` — `(id, order_id, rfq_item_id,
  supplier_id, quote_id, decision_id, line_status, confirmed_at,
  dropped_at, drop_reason, created_at)`

### Enums

```python
class LineDecision(str, enum.Enum):
    USE_FULL = "use_full"
    USE_HALF = "use_half"
    DROP     = "drop"
```

## API surface

New:

```
POST  /api/v1/orders/{order_id}/clarify            # [admin]
POST  /api/v1/orders/{order_id}/answer             # [purchaser]
POST  /api/v1/orders/{order_id}/resolve-clarification  # [admin]
POST  /api/v1/orders/{order_id}/snapshot-eta       # [admin]

GET   /api/v1/supplier-portal/rfqs                 # [supplier]
GET   /api/v1/supplier-portal/rfqs/{rfq_id}        # [supplier]
POST  /api/v1/supplier-portal/rfqs/{rfq_id}/quote  # [supplier]
POST  /api/v1/supplier-portal/quotes/{quote_id}/accept  # [supplier]
GET   /api/v1/supplier-portal/assignments          # [supplier]

GET   /api/v1/rfq/{rfq_id}/lattice                 # [admin]
POST  /api/v1/rfq/{rfq_id}/compose                 # [admin]
POST  /api/v1/orders/{order_id}/approve-proposal   # [purchaser]
POST  /api/v1/orders/{order_id}/drop-supplier      # [admin]
GET   /api/v1/orders/{order_id}/proposal            # [purchaser or admin]
GET   /api/v1/orders/{order_id}/assignments         # [admin]
```

Modified:

- `POST /api/v1/orders` — `OrderItemIn.description` field (intended
  use, forwarded to suppliers as `RFQItem.description`);
  `OrderIn.search_by_impa` flag (informational)

## Identity sealing (unchanged)

The 3-tier redaction in `app/services/redaction.py` is reused as-is:

- **Purchasers** never see supplier names; they see
  `customer_facing_total` (the line total with margin applied).
- **Suppliers** never see the vessel's real name; they see a
  deterministic `vessel_label` (e.g. `Vessel #7`).
- **Admins** see everything.

The supplier portal uses `_anonymize_vessel_name` (CRC32 →
`"Vessel #N"`) on every read. The proposal endpoint uses
`hides_prices(token.roles)` to decide between the sealed shape
(purchaser) and the full shape (admin).

## ETA gating

`marketplace.snapshot_eta` is called by `fan_out_rfq` and writes the
ETA to `order.eta_at_port`. This is a **snapshot**, not a live join.
The order is allowed to proceed if `eta_at_port` is null; a warning
is shown in the marketplace UI when null. The new flow does NOT
block on ETA. The 24h supplier drop is the only real timeout.

## Preparation timeout (the 24h window)

- When the purchaser approves, each winning supplier's
  `preparation_deadline` is set to `now + 24h`
- A FastAPI background task (started in `app/main.py` lifespan)
  runs every 5 minutes, scans for `supplier_line_assignments` where
  `confirmed_at IS NULL AND dropped_at IS NULL AND
  preparation_deadline < now()`, and calls `drop_slow_supplier` for
  each
- `drop_slow_supplier` sets `dropped_at = now()` and
  `drop_reason = "preparation_timeout_24h"`. The line goes back to
  a "needs another supplier" state. No automatic re-bid.
- A notification goes to admin ("Slice for {supplier} on order
  {ref} was dropped for slow confirmation")

## Permissions

New permissions added to `SYSTEM_PERMISSIONS`:

```
("marketplace", "compose",   "global")   # company builds proposal
("marketplace", "approve",   "own")      # purchaser approves proposal
("marketplace", "clarify",   "global")   # company asks for clarification
("marketplace", "drop",      "global")   # company drops slow supplier
("supplier_portal", "view",  "global")   # supplier sees their RFQs
("supplier_portal", "quote", "global")   # supplier submits a quote
("supplier_portal", "accept", "global")  # supplier accepts a slice
```

Role mapping:

- `super_admin` and `fleet_admin` get all of the above
- `purchasing_officer` gets `marketplace:approve:own`
- `supplier` gets the three `supplier_portal:*` permissions

## Tests

`backend/tests/marketplace/` (64 tests, all passing):

- `test_clarification.py` (14) — ask, answer, resolve,
  fan-out blocked by unresolved
- `test_eta_snapshot.py` (6) — happy path, stale AIS, no AIS
- `test_supplier_portal.py` (11) — supplier can only see their own
  RFQs, can submit full/partial/none
- `test_compose_proposal.py` (8) — company decision per line,
  margin applied, customer-facing total computed
- `test_purchaser_approval.py` (10) — approve happy, reject with
  reason, no notifications leak identities
- `test_preparation_timeout.py` (7) — 24h drop runs at deadline,
  manual drop also works
- `test_sealed_identities.py` (8) — supplier sees anonymized vessel,
  purchaser sees sealed suppliers, winner identity never reaches
  losing suppliers

## Frontend

New pages:

- `frontend/src/pages/SupplierPortal.jsx` — list of invited RFQs +
  per-RFQ detail with the per-line full/partial/none picker. Plus a
  "My accepted orders" / assignments tab.
- `frontend/src/pages/Marketplace.jsx` — the lattice (rows = lines,
  cols = suppliers, cells = full/partial/none/no-bid). Per-line
  decision row at the bottom. Margin % input. "Send to purchaser"
  button.

Modified pages:

- `OrderDetail.jsx` — when status is `AWAITING_PURCHASER_APPROVAL`,
  render the composed proposal (per-line total with margin, lead
  time, payment terms) with Approve / Reject buttons. Sealed supplier
  names. When status is `CONFIRMED`, render the preparation status
  panel (green/red, Drop button).
- `OrderCreate.jsx` — per-line "intended use" description textarea
  (forwarded to suppliers as `RFQItem.description`); an IMPA / name
  search-mode toggle in the product picker.
- `Orders.jsx` — added filters for the new statuses
  (`awaiting_clarification`, `quoting`, `ready_for_compose`,
  `awaiting_purchaser_approval`).
- `App.jsx` — removed `/market-sim` and `/market-sim/:rfqId`,
  added `/supplier`, `/supplier/rfq/:rfqId`, `/marketplace`,
  `/marketplace/:rfqId`.
- `Layout.jsx` — replaced "Marketplace Sim" with "Marketplace"
  (admin permission gate); added "Supplier Portal" (supplier role
  gate).
- `MarketSim.jsx` — replaced with a deprecation banner pointing to
  the new pages. The original implementation is at
  `MarketSim.jsx.removed` for any future "compare the two" demo.

New API wrapper:

- `frontend/src/api/marketplace.js` — thin wrapper around
  `apiGet` / `apiPost` for the 10 new endpoints.

## Out of scope

- No Celery — the timeout sweeper is an in-process asyncio task
  in the FastAPI lifespan, not a worker.
- No real supplier email/SMS — `Notification` rows only.
- No margin history (one margin per order, no audit).
- No multi-currency — the order's `currency` carries through;
  suppliers quote in the same currency.
- No partial shipment tracking — `IN_TRANSIT` / `DELIVERED` are
  unchanged.
- No new IMPA codes — we use what's seeded.
- The bid war engine (`market_sim.py`) and its 309 existing tests
  stay but no UI points to it. A future "compare" demo could
  revive it.

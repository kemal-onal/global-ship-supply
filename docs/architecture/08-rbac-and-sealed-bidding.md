# RBAC hardening & sealed-bid RFQ

> Two layers, added on top of the RBAC scaffold from
> [03 — RBAC & network security](03-rbac-security.md):
>
> 1. **Route enforcement + vessel scoping** — every protected route
>    now requires a `require_permission(...)` guard *and* a vessel
>    scope check on the row-level resource.
> 2. **Sealed-bid redaction at the API boundary** — non-admin callers
>    see "Bidder 1, Bidder 2, …" with the winner's total + lead
>    time + score ranking; supplier names, prices, ratings, and
>    subscore breakdowns are stripped from the response. The DB
>    still holds the truth.
>
> Plus a **counter-offer classification rule** on the
> `market_sim_events` audit log: the buyer's counter-offer is
> classified procurement information, visible only to the winning
> supplier (and admins).

---

## 1. The sealed-bid principle

A sealed bid is a bid whose **identity is hidden** from the buyer
until they commit to an award. In real procurement, the buyer sees a
ranked list of bids with the winner's full price, but not the
*names* of the losing bidders or their per-bid prices — only the
*winner* needs to know what the competition looked like, and only
because the buyer is about to call them.

The platform implements this as a **response-side filter**, not a
data-model flag. Why:

- The DB always holds the truth. Audits, the counter-offer workflow,
  and the eventual supplier portal all need the real numbers.
- A single RFQ can be viewed sealed by a purchaser and unsealed by
  an admin in the same session — there's no per-RFQ mode to track.
- A `sealed_bid_mode` flag would require every consumer to check it,
  including the audit log. Filtering at the boundary is simpler and
  harder to bypass.

The redaction lives in one file:
`backend/app/services/rfq_serializers.py`. The two entry points are
`seal_comparison_response` (for the read paths) and `seal_events`
(for the event log timeline).

---

## 2. What changes for the caller's view

### 2.1 Unsealed (admin / fleet_admin)

`POST /rfq/{id}/compare` and `POST /rfq/{id}/simulate` return the
full shape: supplier names, supplier ids, per-bidder prices,
reliability/quality ratings, subscore breakdown, winner id.

```json
{
  "results": [
    {
      "quote_id": "…",
      "supplier_id": "…",
      "supplier_name": "APM Marine Supply",
      "total": 4250.00,
      "currency": "USD",
      "lead_time_days": 5,
      "reliability": 4.7,
      "quality": 4.5,
      "subscores": { "price": 0.91, "lead_time": 0.85, "reliability": 0.94, "quality": 0.90 },
      "score": 0.91
    },
    …
  ],
  "winner": "<quote_id>"
}
```

### 2.2 Sealed (everyone else)

The same call, with a `purchasing_officer` JWT, returns:

```json
{
  "results": [
    { "rank": 1, "label": "Bidder 1", "total": 4250.00, "currency": "USD", "lead_time_days": 5,  "score": 0.91 },
    { "rank": 2, "label": "Bidder 2", "total": null,    "currency": null,   "lead_time_days": null, "score": 0.84 },
    { "rank": 3, "label": "Bidder 3", "total": null,    "currency": null,   "lead_time_days": null, "score": 0.77 }
  ],
  "winner_rank": 1
}
```

Note the lossy bits:

- `supplier_id`, `supplier_name`, `quote_id`, `reliability`,
  `quality`, `subscores` are dropped.
- Losers' `total` and `lead_time_days` are nulled.
- The explicit `winner` id is replaced with `winner_rank` (1 if
  there's a winner, else null).
- The `currency` field on losers is also nulled — a cheap
  side-channel fix that prevents a sophisticated caller from
  inferring the winner's currency.

### 2.3 Event log redaction

The `/simulate` response includes a per-event timeline. The
serializer:

- Drops `supplier_id` from every event (so a `bid_arrived` event no
  longer tells the caller which bidder produced it).
- Replaces `counter_offer` events with `visibility=winner_only` and
  a payload that's not in the caller's `visible_to_supplier_ids`
  with a stub: `{"redacted": true, "summary": "Counter-offer sent
  to winner"}`.

This is what a `purchasing_officer` sees on the bid-war timeline
after a round 2 with a counter-offer:

```
18:42:13  bid arrived          Bidder 1      $4,250.00 · 5d lead
18:42:14  bid arrived          Bidder 2      $4,400.00 · 4d lead
18:42:15  round close          3 bids scored
18:42:20  counter offer        Counter-offer sent to winner     ← redacted
18:42:30  bid arrived          Bidder 1      $3,980.00 · 3d lead
…
```

The same timeline as `super_admin`:

```
18:42:13  bid arrived          APM Marine Supply  $4,250.00 · 5d lead
18:42:14  bid arrived          BunkerOne          $4,400.00 · 4d lead
18:42:15  round close          3 bids scored
18:42:20  counter offer        {"lead_days": 3, "price_cap": 4200}   ← full terms
18:42:30  bid arrived          APM Marine Supply  $3,980.00 · 3d lead
…
```

---

## 3. Counter-offer classification

Counter-offer terms are **classified procurement information**: if
the losing bidders see what the buyer asked of the winner, they
can game round 2 to undercut the target exactly. The platform
prevents this leak at three layers.

### 3.1 The data model

`market_sim_events` has two new columns (migration `0004`):

| Column | Type | Notes |
|---|---|---|
| `visibility` | `VARCHAR(20) NOT NULL DEFAULT 'public'` | `'public'` or `'winner_only'` |
| `visible_to_supplier_ids` | `UUID[] NULL` | Populated with `[winner.supplier_id]` for `counter_offer` events |

Existing rows backfill to `visibility='public'`. A `CheckConstraint`
constrains the value at the DB level so a bad write from a future
code path can't smuggle a typo past the application.

### 3.2 The engine

`run_market_sim` (`backend/app/services/market_sim.py`) tags the
`counter_offer` event with `visibility=winner_only` and
`visible_to_supplier_ids=[winner.supplier_id]`. The other round-2
`bid_arrived` events are still `visibility=public` (so the buyer
sees the new bids on the timeline) — only the *counter-offer
itself* is classified.

### 3.3 The serializer

The response serializer in `rfq_serializers.py::seal_event` reads
`visibility` and `visible_to_supplier_ids` to decide what to return:

- If `caller_roles` is unsealed (admin / fleet_admin), return the
  event untouched.
- If `caller_supplier_id` is in `visible_to_supplier_ids` (the
  winning supplier), return the event with the full payload.
- Otherwise, drop the `payload` and replace it with
  `{"redacted": true, "summary": "Counter-offer sent to winner"}`,
  and drop `visibility` / `visible_to_supplier_ids` from the event
  (so the caller doesn't learn the structure of the rule even if
  they don't learn the content).

### 3.4 Why no supplier portal yet

The supplier role exists in the seed but there's no `/supplier`
route group, no supplier login flow, and no inbox UI. The
`visible_to_supplier_ids` field is populated correctly today so
the moment a supplier endpoint queries the event log, the rule is
already in place — no migration to ship when the portal lands.

---

## 4. Vessel scoping

A `purchasing_officer` on vessel 0 must not see RFQs / orders
belonging to vessel 1, 2, 3, or 4. The check is a row-level scope
filter that runs after `require_permission` (which checks the
*role* permission) and before the resource is loaded into the
response (which would expose its contents).

### 4.1 The helper

`backend/app/deps/auth.py::assert_vessel_access(token, vessel_id)`:

```python
def has_vessel_access(token: CurrentToken, vessel_id: UUID | None) -> bool:
    if token.has_any_role(["super_admin", "fleet_admin"]):
        return True
    if token.vessel_id is None:
        # External user (supplier) or vessel-unaffiliated user — they
        # must not get access to vessel-scoped resources.
        return False
    return str(token.vessel_id) == str(vessel_id)


async def assert_vessel_access(token: CurrentToken, vessel_id: UUID | None) -> None:
    if not has_vessel_access(token, vessel_id):
        # 404, not 403, so we don't leak resource existence to
        # someone who shouldn't know about the other vessel.
        raise HTTPException(status_code=404, detail="Not found")
```

### 4.2 Where it's applied

Every RFQ route in `backend/app/api/v1/rfq.py` calls
`await assert_vessel_access(token, rfq.order.vessel_id)`. The list
route additionally filters the SQL query by `Order.vessel_id ==
token.vessel_id` for non-admins, so a non-admin never even knows
the other vessels' RFQs exist.

The 404 (vs. 403) is intentional: a 403 confirms the resource
exists, which is itself a leak across vessels.

### 4.3 Why not Postgres RLS?

Row-level security would be more "correct" but it's a 3-day project
to land safely. The Python-side filter does the same job for v1;
the call site is one line per route and is testable in
`tests/api/test_rbac.py` with a 404 assertion. RLS is on the
follow-up list for when the platform grows past one tenant.

---

## 5. The `/permissions` page

Every authenticated user has a `/permissions` page in the sidebar.
It serves two purposes:

1. **Self-view for everyone.** "You are signed in as {name}, with
   roles {chips}, vessel {id or '—'}. Here are the {N}
   permission strings currently in your JWT, grouped by resource."
2. **Governance slide for admins.** "Here is the full role ×
   permission matrix, with green checks where the DB has a grant.
   Hit 'Copy as markdown' to grab the table for the slide
   handout."

Non-admins get a 403 on `GET /permissions/matrix`; the page handles
that by rendering an "Admin-only view" notice instead of an error
toast.

### 5.1 Endpoints

| Endpoint | Auth | Returns |
|---|---|---|
| `GET /api/v1/permissions/me` | Any authenticated | `{user: {sub, roles, vessel_id}, permissions: [...]}` |
| `GET /api/v1/permissions/matrix` | super_admin / fleet_admin | `{roles, permissions, role_permissions}` |

The `/me` endpoint is intentionally open to all authenticated
callers — it returns only the caller's own info, which they
already have via their JWT. The `/matrix` endpoint is admin-only
because it exposes the *complete* RBAC shape; non-admins don't
need to know the global matrix, only their own view.

### 5.2 Why a page, not a CLI

The platform is read-only from the role-management perspective
in the demo (no "grant this permission to this user" UI). The
`/permissions` page is the demo's governance slide: it shows that
the RBAC shape is real, that the caller's scope is what the
backend enforces, and that the matrix isn't a fiction.

---

## 6. The role-aware UI

The frontend gates every page and every nav item on the caller's
roles + permissions. The pattern is two-line:

```jsx
// Sidebar — hide nav items the user can't use.
const visibleNav = useMemo(() => nav.filter(item => {
  if (item.roles && !item.roles.some(r => hasRole(r))) return false
  if (item.permissions && !item.permissions.every(([res, act, sc]) => hasPermission(res, act, sc))) return false
  return true
}), [hasRole, hasPermission])

// MarketSim — show "Sealed-bid view" pill for non-admins.
const sealedBid = !hasRole('super_admin', 'fleet_admin')
```

A hidden nav item is also a hidden route, so a purchaser who
manually types `/admin` into the URL still gets a 403 from the
API. Belt and braces.

### 6.1 The MarketSim sealed view

For non-admins, the bid-war view:

- Shows a **"Sealed-bid view"** pill in the header.
- Replaces supplier names with "Bidder 1, Bidder 2, …" in the
  leaderboard table.
- Hides the per-bidder price ladder, the reliability/quality
  ratings, the "why this winner" stacked bar, and the price ×
  lead-time scatter — all of which would leak the redacted fields.
- Renders the counter-offer event as "Counter-offer sent to
  winner" (redacted stub) instead of the full terms.

The what-if weight sliders and the round-1/round-2 toggle stay
visible — they don't leak any sealed fields, and a purchaser
iterating on weights to see how the ranking changes is a useful
demo.

### 6.2 The RFQ page "Re-rank bids (sealed)" button

Same endpoint as before (`POST /rfq/{id}/compare`), different
label and tooltip:

| Role | Button label | Tooltip |
|---|---|---|
| `super_admin` / `fleet_admin` | "Compare bids" | "Compare all bids and pick a winner (full leaderboard)." |
| everyone else | "👁 Re-rank bids (sealed)" | "You will see the winner and the ranking. Supplier identities are hidden until the award is committed by an admin." |

The label change is a UX hint, not a security boundary. The
sealed shape is enforced at the API boundary regardless of what
the button says.

---

## 7. Test coverage

The new behavior is locked down by three test files:

- `tests/api/test_rbac.py` (27 tests) — vessel-scope 404s, role
  permission checks, `/permissions/me` open to all,
  `/permissions/matrix` admin-only, sealed shape for
  `purchasing_officer`, unsealed shape for `super_admin`.
- `tests/api/test_counter_offer_visibility.py` (12 tests) —
  engine tags the event with `visibility=winner_only` and
  `visible_to_supplier_ids=[winner]`, the response serializer
  returns the full payload to admin, the redacted stub to
  purchaser, and the full payload to the winning supplier (when
  the supplier portal lands).

Plus regression fixes in the pre-existing tests:

- `test_market_sim.py` — fake token / fake RFQ now share a
  `_TEST_VESSEL` UUID, so the new `assert_vessel_access` call
  doesn't 404 the test.
- The `require_permission` factory had a latent bug
  (`token.has_permission(resource, action, scope)` was being
  called with 3 args, but the method takes 1 joined string). It
  was only caught because the new routes actually call the
  factory for the first time.

The full suite is at **285 tests passing in ~7s**.

---

## 8. What this doc explicitly does not cover

- **Per-vessel price ceilings or purchase approval chains.** A
  follow-up. The demo shows visibility, not workflow.
- **Encrypting supplier names at rest.** Not needed; the sealed-bid
  redaction is at the API boundary, and the DB holds the truth
  (admin can still see it). This is consistent with how real
  procurement systems work.
- **A "sealed bid" mode toggle on the RFQ itself.** Same reason —
  the data model doesn't need to know. The serializer decides.
- **Migration to row-level security in Postgres.** On the
  follow-up list; the Python-side filter does the job for v1.
- **A `/users` management page for admins.** Out of scope; the
  `/permissions` page is read-only. Live role-grant UI can come
  in a follow-up.
- **A full supplier portal.** The `supplier` role exists in the
  seed but the portal doesn't ship in this iteration. The
  `visible_to_supplier_ids` field is populated correctly today,
  so the rule is ready the moment a supplier endpoint queries the
  event log.

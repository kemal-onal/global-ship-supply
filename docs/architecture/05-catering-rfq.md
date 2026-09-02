# Catering & supplier bidding

> Two of the differentiating features for AVS Global:
> 1. **Provisioning plans** that respect per-nationality calorie targets
>    and voyage duration
> 2. **Dynamic supplier RFQ** with weighted bid comparison

---

## 1. Catering / provisioning

### 1.1 Inputs

- Vessel (crew capacity)
- Voyage start / end dates
- Crew breakdown by nationality (e.g. 12 Filipino, 8 Indian, 4 European)
- Daily menu templates per nationality × meal type

### 1.2 Algorithm

```python
def compute_voyage_plan(vessel, start, end, crew_by_nat, buffer_days=2, buffer_pct=0.10):
    days = (end - start).days + 1
    plan_days = days + buffer_days

    # Per-day per-nationality calorie target
    per_nat = {}
    for nat, n in crew_by_nat.items():
        per_nat[nat] = n * nation_calorie_target(nat) * plan_days

    # Allocate across meals: breakfast 25%, lunch 35%, dinner 40%
    grand_total = sum(per_nat.values())
    distribution = MEAL_DISTRIBUTION  # {breakfast, lunch, dinner}

    # Look up menu template per (nationality, meal_type)
    # For each template item: scale quantity by (per_nat * meal_share / item_calories)

    items = aggregate_product_quantities(...)
    return ProvisioningPlan(items=items, total_calories=grand_total, days=plan_days)
```

### 1.3 Why nationality matters

A Filipino crew member's traditional diet relies on rice, fish, and
vegetables (~2,800 kcal target). A European crew member expects bread,
cheese, red meat (~3,200 kcal). Feeding everyone the same European
menu wastes food and undernourishes ~60% of the crew.

The menu templates are seeded per (nationality, meal_type) in
`scripts/seed.py` and can be edited in the admin UI.

### 1.4 Output

A `ProvisioningPlan` with:

- `total_calories` — daily × crew × days
- `items[]` — aggregated SKU list with quantities, units, and estimated cost
- `days` — voyage days + buffer

The chef/steward reviews the basket, edits if needed, and submits it
as a regular order. No custom workflow required.

---

## 2. RFQ & supplier bidding

### 2.1 Lifecycle

```
draft → open → closed → awarded
                ↓
            cancelled
```

1. **Draft**: purchaser picks a pending order and clicks "Send RFQ"
2. **Open**: backend looks up suppliers with `supplier_ports.port_id == order.port_id`
   and creates a `supplier_quotes` row (status=open) for each
3. **Closed**: each supplier submits a quote through the supplier portal
   (or via email + manual entry by the purchaser)
4. **Awarded**: purchaser runs the comparison, picks a winner, the order
   status moves to `confirmed` and a PO is generated

### 2.2 Quote comparison

`compare_quotes(rfq_id, weights)` returns a ranked list with scores in
0–1:

```python
def score(quote, weights):
    # Normalize each dimension
    price_n    = 1 - (quote.price - min_price) / (max_price - min_price)
    lead_n     = 1 - (quote.lead_time_days - min_lead) / (max_lead - min_lead)
    reliability = supplier.reliability_rating / 5.0
    quality   = supplier.quality_rating / 5.0

    return (
        weights.price        * price_n
      + weights.lead_time   * lead_n
      + weights.reliability * reliability
      + weights.quality     * quality
    )
```

Weights default to `{price: 0.4, lead_time: 0.2, reliability: 0.2, quality: 0.2}`
and are overridable per RFQ.

### 2.3 Anti-gaming

- **Quote binding**: once a supplier's quote is `awarded`, they cannot
  edit it; the PO references the immutable quote row.
- **Time-boxing**: RFQs default to 72h; late quotes return 422.
- **Multiple winners**: a single RFQ can split the basket across N
  suppliers (lowest combined score), not necessarily one winner.

### 2.4 Supplier scoring (long-term)

`supplier_ratings` accumulates:

- `reliability_rating` (1–5): % of POs delivered on time
- `quality_rating` (1–5): average of post-delivery survey
- `communication_rating` (1–5): response time
- `on_time_pct`: rolling 12-month metric

These feed into future RFQ comparisons and surface on the supplier
leaderboard on the Dashboard.

---

## 3. Customs / regulation filter

`evaluate_order(order)` runs each line item against the destination
country's rules:

```python
def evaluate_order(order):
    port = port_repo.get(order.port_id)
    country = port.country
    issues = []
    for item in order.items:
        for rule in country.rules:
            if _matches(item, rule.condition):
                issues.append(Issue(
                    severity=rule.severity,
                    title=rule.name,
                    description=rule.description,
                    requires_permit=rule.requires_permit,
                ))
    return EvaluationResult(
        issues=issues,
        blocking=any(i.severity == 'blocking' for i in issues),
    )
```

The condition language is JSONLogic-lite:

```json
{ "and": [
    { "==": [{"var": "category"}, "weapons"] },
    { "in": [{"var": "destination_country"}, ["IN", "ID"]] }
]}
```

Evaluated by a 30-line recursive function in
`backend/app/services/customs.py` — no external rules engine dependency.

---

## 4. Integration points

- Order creation → customs evaluation (always)
- Order status `pending_approval` → RFQ creation (manual)
- RFQ `awarded` → order status `confirmed`
- Order status `confirmed` → provisioning plan (if catering order)

"""
Three-tier trust redaction for the AVS Global hidden market.

The DB always holds the truth. This module is the response-side filter
that shapes what each caller class sees:

* **Company** (super_admin, fleet_admin, vessel_captain, chief_steward,
  port_authority, viewer) — every field is visible. These roles are
  the omniscient side.
* **Purchaser** (``purchasing_officer``) — sees only the request
  itself: products, quantities, status, dates. No unit prices, no
  line totals, no grand totals, no supplier names, no bid-war
  details. After the bid war runs, the purchaser sees only the
  winning bid's lead time + price. Winner identity stays sealed.
* **Supplier** (``supplier``) — sees the order context with the
  vessel anonymized, ``internal_notes`` stripped, ``created_by``
  identity stripped. ``customer_notes`` and per-line
  ``OrderItem.notes`` stay visible — they're written for the
  supplier, not about them. Sees the sealed bid war (other bidders
  as ``Bidder N``) and the order they're fulfilling.

Why response-side (and not a ``sealed_bid_mode`` flag on the row):
  * The DB always holds the truth — admin views, audits, and the
    counter-offer workflow need the real numbers regardless of who
    is asking.
  * The "sealed" property is a *role* concern, not a *data*
    concern. A single order can be viewed sealed by a purchaser
    and unsealed by a super_admin in the same session.
  * A ``sealed`` flag would require every consumer to check the
    flag, including the audit log. Filtering at the boundary is
    simpler and harder to bypass.

Pattern reuse: this module is the natural extension of
``app.services.rfq_serializers``. The redaction predicates and the
filter functions are pure — they take a payload dict and a caller
roles list and return a new payload dict. No DB access, no
framework imports.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any


# --- Role predicates --------------------------------------------------

# Roles that see the company-wide unsealed view. Anything outside
# this list gets a sealed/redacted shape. Matches the RFQ sealed-bid
# rule (rfq_serializers.UNSEALED_ROLES) so the two layers stay
# consistent.
UNSEALED_ROLES = frozenset({
    "super_admin",
    "fleet_admin",
    "vessel_captain",
    "chief_steward",
    "port_authority",
    "viewer",
})

# Purchasers see only the request — every monetary field and every
# supplier identity is stripped. The awarded-RFQ view is reduced to
# a one-card "winner total + lead days + payment terms" payload.
PRICE_HIDING_ROLES = frozenset({"purchasing_officer"})

# Suppliers see the order context with the vessel anonymized, the
# internal notes stripped, and the created_by identity removed.
SUPPLIER_ROLES = frozenset({"supplier"})


def is_unsealed(caller_roles: list[str] | None) -> bool:
    if not caller_roles:
        return False
    return any(r in UNSEALED_ROLES for r in caller_roles)


def hides_prices(caller_roles: list[str] | None) -> bool:
    if not caller_roles:
        return False
    return any(r in PRICE_HIDING_ROLES for r in caller_roles)


def is_supplier(caller_roles: list[str] | None) -> bool:
    if not caller_roles:
        return False
    return any(r in SUPPLIER_ROLES for r in caller_roles)


# --- Order payload filters --------------------------------------------

# Top-level monetary fields on the order. Each is set to None for
# the purchaser; the row still ships so the schema is stable for
# the frontend.
_ORDER_MONETARY_FIELDS = (
    "subtotal",
    "tax_total",
    "shipping_total",
    "grand_total",
)

# Per-item monetary fields. Same treatment.
_ITEM_MONETARY_FIELDS = (
    "unit_price",
    "line_total",
)


def seal_order_for_purchaser(payload: dict[str, Any]) -> dict[str, Any]:
    """Strip every monetary value from an order payload.

    The purchaser sees: reference, status, priority, dates, vessel
    (full identity), port (full identity), items with product name +
    SKU + quantity + unit, customer_notes, internal_notes, source,
    regulation_warnings. No currency, no totals, no per-item prices.

    IMPA-first redesign (migration 0007): the order line carries
    no price in the wire payload at all. The redaction no longer
    injects ``unit_price`` / ``line_total`` keys for the
    purchaser — they simply aren't in the payload. We still null
    them out if a future caller does emit them, so the rule is
    forward-compatible.
    """
    out = deepcopy(payload)
    for field in _ORDER_MONETARY_FIELDS:
        out[field] = None
    out["currency"] = None
    items = out.get("items") or []
    for item in items:
        for field in _ITEM_MONETARY_FIELDS:
            # Only null out if the field is already in the
            # payload. The IMPA-first wire contract doesn't
            # emit these keys; the redaction shouldn't add
            # them back.
            if field in item:
                item[field] = None
    out["items"] = items
    return out


def seal_order_for_supplier(payload: dict[str, Any]) -> dict[str, Any]:
    """Anonymize the order for a supplier caller.

    Stripped:
      * ``vessel_id`` + ``vessel_name`` — replaced with a
        deterministic ``vessel_label`` so the supplier sees the same
        label for the same vessel across requests (and across the
        RFQ + order views).
      * ``internal_notes`` — buyer-side procurement strategy.
      * ``created_by`` — caller identity of the order creator.
      * ``customer_notes`` is **kept** — it's written *to* the
        supplier (gate codes, delivery windows, contact channels).
      * Per-line ``OrderItem.notes`` is **kept** — same rationale.

    Monetary fields (subtotal, grand_total, unit_price, line_total)
    are visible to the supplier — they're the one fulfilling the
    order and need to know what to bill. If this ever needs to
    change, drop the relevant fields to None here.
    """
    out = deepcopy(payload)
    vessel_id = out.get("vessel_id")
    out["vessel_id"] = None
    out["vessel_name"] = None
    if vessel_id:
        out["vessel_label"] = _vessel_label(vessel_id)
    out["internal_notes"] = None
    out["created_by"] = None
    return out


# --- Catalog payload filters ------------------------------------------


def seal_catalog_for_purchaser(payload: dict[str, Any]) -> dict[str, Any]:
    """Strip the list price from a catalog response.

    The catalog has two shapes:

    * list: ``{"items": [...], "total": int, ...}``
    * detail: a flat product dict

    This function handles both. The product list inside ``items``
    is also redacted.
    """
    if not isinstance(payload, dict):
        return payload
    if "items" in payload and isinstance(payload["items"], list):
        out = deepcopy(payload)
        out["items"] = [seal_product_for_purchaser(p) for p in out["items"]]
        return out
    return seal_product_for_purchaser(payload)


def seal_product_for_purchaser(product: dict[str, Any]) -> dict[str, Any]:
    """Drop the list price + currency from a single product dict.

    Keeps: id, sku, name, short_name, description, category,
    status, unit, in_stock, stock_qty, lead_time_days, manufacturer,
    part_number, hs_code, is_hazardous, is_perishable, etc.
    Drops: unit_price, currency.
    """
    out = deepcopy(product)
    out["unit_price"] = None
    out["currency"] = None
    return out


# --- RFQ award payload filter -----------------------------------------


def seal_rfq_award_for_purchaser(
    rfq_payload: dict[str, Any],
    comparison: dict[str, Any] | None,
) -> dict[str, Any]:
    """Reduce an awarded RFQ to a one-card winner summary.

    The purchaser's post-award view: ``winner_total``, ``winner_lead_days``,
    ``winner_payment_terms``, ``score`` (the winner's). No supplier
    name, no other bidders, no sub-scores, no weights.
    """
    out = deepcopy(rfq_payload)
    if not comparison:
        out["results"] = []
        out.pop("winner", None)
        out["winner_rank"] = None
        return out
    results = comparison.get("results") or []
    winner_id = comparison.get("winner")
    winner_row = next(
        (r for r in results if str(r.get("quote_id") or r.get("supplier_id") or "") == str(winner_id or "")),
        None,
    )
    if not winner_row and results:
        # compare_quotes's seal layer may have replaced the winner id
        # with a rank; fall back to the highest-scoring row.
        winner_row = max(results, key=lambda r: r.get("score") or 0.0)
    if not winner_row:
        out["results"] = []
        out.pop("winner", None)
        out["winner_rank"] = None
        return out
    out["results"] = [{
        "winner_total": float(winner_row.get("total") or 0.0),
        "winner_currency": winner_row.get("currency"),
        "winner_lead_days": winner_row.get("lead_time_days"),
        "winner_payment_terms": winner_row.get("payment_terms"),
        "winner_score": winner_row.get("score"),
    }]
    out.pop("winner", None)
    out["winner_rank"] = 1
    return out


# --- Vessel label ------------------------------------------------------


def _vessel_label(vessel_id: str | Any) -> str:
    """Deterministic, opaque vessel label for supplier callers.

    ``hash()`` is salted per Python process, so we use a stable
    checksum (CRC32 of the UUID string mod 10_000) instead. Same
    vessel → same label across requests; different vessels → very
    likely different labels.
    """
    import zlib
    s = str(vessel_id)
    n = zlib.crc32(s.encode("utf-8")) % 10_000
    return f"Vessel #{n:04d}"


__all__ = [
    "UNSEALED_ROLES",
    "PRICE_HIDING_ROLES",
    "SUPPLIER_ROLES",
    "is_unsealed",
    "hides_prices",
    "is_supplier",
    "seal_order_for_purchaser",
    "seal_order_for_supplier",
    "seal_catalog_for_purchaser",
    "seal_product_for_purchaser",
    "seal_rfq_award_for_purchaser",
]

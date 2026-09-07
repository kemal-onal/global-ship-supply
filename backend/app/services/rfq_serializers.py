"""
Sealed-bid serializer for RFQ comparison + market-sim results.

The data model (SupplierQuote, BidComparison, MarketSimEvent) holds
the full truth. This module is the *response-side* filter that
strips identity, ratings, and per-bidder prices for callers who
shouldn't see them — e.g. a `purchasing_officer` running the bid
war before the award is committed by an admin.

Why response-side (not a `sealed_bid_mode` flag on the RFQ):
  * The DB always holds the truth. Admin views, audits, and the
    counter-offer workflow need the real numbers regardless of who
    is asking.
  * The "sealed" property is a *role* concern, not a *data* concern.
    A single RFQ can be viewed sealed by a purchaser and unsealed
    by a super_admin in the same session.
  * A `sealed_bid_mode` flag would require every consumer to check
    the flag, including the audit log. Filtering at the boundary
    is simpler and harder to bypass.

Rule summary (for non-admin callers):
  * Each result row is replaced with a `Bidder {n}` label (1-indexed,
    ordered by score descending — rank 1 is the winner).
  * `supplier_name`, `supplier_id`, `quote_id`, `reliability`,
    `quality`, and `subscores` are dropped.
  * The winner's `total` and `lead_time_days` are kept verbatim.
    Losers' `total` and `lead_time_days` are redacted to `None`.
  * The `score` column is kept for every row, so the ranking is
    visible without leaking prices.
  * Per-event timeline: events with `event_type=counter_offer` and
    `visibility=winner_only` get a redacted stub ("Counter-offer
    sent to winner") for non-admin callers; the rest of the timeline
    is filtered to drop the `supplier_id` field on each event
    (so the bidder identities stay hidden even on the audit log).
"""
from __future__ import annotations

from typing import Any
from uuid import UUID


# Roles that see the unsealed view. Anything outside this list gets
# the sealed (redacted) shape. Keep this list narrow — every entry
# is a deliberate decision to expose supplier identity.
UNSEALED_ROLES = frozenset({"super_admin", "fleet_admin"})


def _is_unsealed(caller_roles: list[str] | None) -> bool:
    if not caller_roles:
        return False
    return any(r in UNSEALED_ROLES for r in caller_roles)


def _winner_id_from_results(results: list[dict[str, Any]], winner: Any) -> str | None:
    """Pull the winner's id from the explicit ``winner`` field, OR
    fall back to the highest-scoring row.

    ``compare_quotes`` returns ``winner`` as the quote id; the dry-run
    scorer in ``market_sim`` returns the supplier id. We need to
    check both because the serializer doesn't know which engine ran.
    """
    if winner:
        return str(winner)
    if not results:
        return None
    top = max(results, key=lambda r: r.get("score") or 0.0)
    return str(top.get("quote_id") or top.get("supplier_id") or "")


def seal_results(
    results: list[dict[str, Any]],
    winner: Any,
    caller_roles: list[str] | None,
) -> list[dict[str, Any]]:
    """Return the results list in the caller's view shape.

    Admin (or fleet_admin): same list, untouched.
    Everyone else: redacted ``Bidder {n}`` rows; only the winner's
    total + lead time; no name/id/ratings/subscores.
    """
    if _is_unsealed(caller_roles):
        return results

    winner_id = _winner_id_from_results(results, winner)
    # Sort by score desc, then assign rank. Stable sort on id breaks
    # ties deterministically.
    ordered = sorted(
        results,
        key=lambda r: (-(r.get("score") or 0.0), str(r.get("quote_id") or r.get("supplier_id") or "")),
    )
    sealed: list[dict[str, Any]] = []
    for idx, r in enumerate(ordered, start=1):
        row_id = str(r.get("quote_id") or r.get("supplier_id") or "")
        is_winner = bool(winner_id) and row_id == winner_id
        sealed.append({
            "rank": idx,
            "label": f"Bidder {idx}",
            "total": float(r["total"]) if is_winner and r.get("total") is not None else None,
            "currency": r.get("currency") if is_winner else None,
            "lead_time_days": r.get("lead_time_days") if is_winner else None,
            "score": r.get("score"),
        })
    return sealed


def seal_comparison_response(
    payload: dict[str, Any],
    caller_roles: list[str] | None,
) -> dict[str, Any]:
    """Top-level filter for the ``compare_quotes`` + ``run_market_sim`` response.

    The input shape (from either engine) is::

        {
          "results":  [{"supplier_name": ..., "supplier_id": ...,
                        "quote_id": ..., "total": ..., ...}, ...],
          "winner":   "<quote_id or supplier_id>",   # may be None
          "weights":  {...},
          ...other engine-specific keys (events, round, etc.)
        }

    For sealed callers, ``results`` is replaced with the redacted
    shape, ``winner`` becomes ``winner_rank`` (1 if there's a winner,
    else None), and every other top-level key is preserved.

    For unsealed callers, the payload is returned untouched.
    """
    if _is_unsealed(caller_roles):
        return payload

    results = payload.get("results") or []
    winner = payload.get("winner")
    sealed_results = seal_results(results, winner, caller_roles)
    out = dict(payload)
    out["results"] = sealed_results
    # Replace the explicit winner id with a rank — "rank 1" is more
    # useful to the caller than "winner id <uuid>" since they can't
    # act on the id anyway.
    if winner is None:
        out["winner_rank"] = None
    else:
        out["winner_rank"] = 1 if sealed_results else None
    # Drop the raw winner id — it would leak the quote/supplier id
    # through the unsealed field on the sealed view.
    out.pop("winner", None)
    return out


# ─── Event-log redaction ────────────────────────────────────────────
#
# `run_market_sim` returns a list of event dicts. Each one looks like:
#   {"id", "ts", "round", "event_type", "supplier_id", "payload": {...}}
#
# For sealed callers:
#   * Every event has its `supplier_id` field dropped (so a
#     `bid_arrived` event no longer tells the caller which bidder
#     produced it).
#   * `counter_offer` events with `visibility == "winner_only"` are
#     reduced to a stub payload ({"redacted": True, "summary":
#     "Counter-offer sent to winner"}); the `terms` (target prices,
#     lead-time squeeze) are classified procurement information and
#     are not exposed to non-admin, non-winner callers.
#   * `counter_offer` events with `visibility == "public"` (legacy /
#     future rows) keep their payload but still drop `supplier_id`.


def seal_event(
    event: dict[str, Any],
    caller_roles: list[str] | None,
    caller_supplier_id: UUID | str | None = None,
) -> dict[str, Any]:
    """Return one event dict in the caller's view shape.

    ``caller_supplier_id`` is the supplier id from the JWT (only
    relevant when a supplier ever calls this endpoint — the buyer
    roles don't have one). For the demo today, no supplier endpoint
    exists, so this is a future-proofing parameter.
    """
    if _is_unsealed(caller_roles):
        return event

    out = dict(event)
    # Always drop supplier identity on the event log.
    out.pop("supplier_id", None)

    if event.get("event_type") == "counter_offer" and event.get("visibility") == "winner_only":
        # Is the caller the winner? They get the full payload; no one
        # else does.
        visible_to = event.get("visible_to_supplier_ids") or []
        if caller_supplier_id and str(caller_supplier_id) in [str(v) for v in visible_to]:
            return out  # winner sees terms
        out["payload"] = {
            "redacted": True,
            "summary": "Counter-offer sent to winner",
        }
        # Also drop the visibility/visible_to fields on the redacted
        # view — they would tell the caller the structure of the rule
        # without revealing the content.
        out.pop("visible_to_supplier_ids", None)
        out.pop("visibility", None)
    return out


def seal_events(
    events: list[dict[str, Any]],
    caller_roles: list[str] | None,
    caller_supplier_id: UUID | str | None = None,
) -> list[dict[str, Any]]:
    return [seal_event(e, caller_roles, caller_supplier_id) for e in events]


__all__ = [
    "UNSEALED_ROLES",
    "seal_results",
    "seal_comparison_response",
    "seal_event",
    "seal_events",
]

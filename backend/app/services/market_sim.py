"""
Marketplace Simulator — the engine that drives a supplier bid war.

A "run" is bound to one RFQ. The engine:

1. Loads every active supplier at the RFQ's destination port (via the
   ``SupplierPort`` join), filtered to those that have at least one
   ``ProductSupplier`` row for the RFQ's products in stock.
2. Builds one :class:`SupplierAgent` per eligible supplier. Each agent
   has a deterministic strategy (``aggressive`` / ``balanced`` /
   ``premium`` / ``slow_but_cheap``) derived once from the supplier's
   cached ratings.
3. Round 1 — every eligible agent generates a bid. The bid is
   persisted through the existing :func:`app.services.rfq.submit_quote`
   so the bids show up on ``rfq.quotes`` exactly like real ones.
4. The existing :func:`app.services.rfq.compare_quotes` engine scores
   the bids, marks the winner, and (unless ``dry_run=True``) sets the
   RFQ to ``awarded``.
5. Round 2 — only agents whose round-1 score was within
   ``ROUND_2_MARGIN`` (0.05) of the winner re-bid. The
   ``counter_offer_terms`` payload nudges their bid price downward.
6. A row is written to ``market_sim_events`` for every step so the
   frontend can render a timeline by polling the table.

Why this engine runs in-process (not as a separate ``sim.runner``
process like the AIS simulator) — the work is bounded (5–10 suppliers
× a handful of bids). It completes in tens of milliseconds. A
long-running background process is overkill for a demo; the seam
between this engine and a future "background market sim" package is
the single :func:`run_market_sim` function.
"""
from __future__ import annotations

import enum
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.market_sim import MarketSimEvent, MarketSimEventType
from app.models.supplier import (
    ProductSupplier,
    RFQ,
    RFQItem,
    RFQStatus,
    Supplier,
    SupplierPort,
    SupplierQuote,
    SupplierStatus,
)
from app.services.rfq import compare_quotes, submit_quote


# Strategy → (price_multiplier, lead_time_delta_days).
# The multiplier is applied to the supplier's base unit price for the
# product; the delta is added to the supplier's lead time.
STRATEGY_PARAMS: dict[str, tuple[float, int]] = {
    "aggressive":      (-0.10, -2),
    "balanced":        (-0.05,  0),
    "premium":         ( 0.08,  3),
    "slow_but_cheap":  (-0.18,  7),
}

# Jitter band (added to the multiplier). ±2% is enough to make the
# bid war feel live without making the math noisy.
JITTER_BAND = 0.02

# An agent that has lost a round by more than this margin drops out —
# prevents an infinite re-bid loop on round 2.
ROUND_2_MARGIN = 0.05

# After this many consecutive rounds without winning, an ``aggressive``
# agent drops out (simulates "walking away from a bad deal").
MAX_CONSECUTIVE_LOSSES_AGGRESSIVE = 3

# Min lead time: never below 1 day regardless of strategy.
MIN_LEAD_DAYS = 1


class AgentStrategy(str, enum.Enum):
    AGGRESSIVE = "aggressive"
    BALANCED = "balanced"
    PREMIUM = "premium"
    SLOW_BUT_CHEAP = "slow_but_cheap"


@dataclass
class Bid:
    """The result of one :meth:`SupplierAgent.generate_bid` call."""

    supplier_id: UUID
    line_items: list[dict[str, Any]]   # [{product_id, quantity, unit_price}]
    lead_time_days: int
    strategy: str
    base_total: float                  # the baseline price before strategy adjustment
    adjusted_total: float              # the final price the agent is bidding

    def as_payload(self) -> dict[str, Any]:
        return {
            "supplier_id": str(self.supplier_id),
            "lead_time_days": self.lead_time_days,
            "strategy": self.strategy,
            "base_total": round(self.base_total, 4),
            "adjusted_total": round(self.adjusted_total, 4),
            "line_items": self.line_items,
        }


@dataclass
class SupplierAgent:
    """An in-memory bidder. One per eligible supplier per run.

    The agent's RNG is seeded with ``(run_seed, supplier_id)`` so the
    same supplier in the same run always produces the same bid. This
    is what makes replays deterministic and the frontend's "what-if
    weight slider" stable.
    """

    supplier_id: UUID
    supplier_name: str
    rating_reliability: float
    rating_quality: float
    on_time_pct: float
    avg_response_hours: float
    currency: str
    # product_id -> unit_price (cached from ProductSupplier on init)
    base_unit_prices: dict[UUID, float]
    base_lead_days: int
    rng_seed: int
    strategy: AgentStrategy

    # Mutated by the engine across rounds.
    consecutive_losses: int = 0
    dropped_out: bool = False

    def generate_bid(
        self,
        *,
        rfq_id: UUID,
        round_n: int,
        rfq_items: list[RFQItem],
        counter_offer_terms: dict[str, Any] | None = None,
    ) -> Bid:
        """Compute a single bid. Pure function of inputs + self.

        ``counter_offer_terms`` lets the buyer squeeze round-2 prices:
        a key like ``"lead_days"`` caps the lead time, a key like
        ``"<product_id>"`` (string form) sets a hard price cap.
        """
        rng = random.Random(self.rng_seed + round_n * 1_000_003)
        price_mult, lead_delta = STRATEGY_PARAMS[self.strategy.value]
        jitter = rng.uniform(-JITTER_BAND, JITTER_BAND)
        multiplier = 1.0 + price_mult + jitter

        # Counter-offer squeeze: if the buyer set a target price for
        # this product, use min(our_price, target). If the buyer set
        # lead_days, cap it.
        co_lead_cap: int | None = None
        if counter_offer_terms:
            if "lead_days" in counter_offer_terms:
                co_lead_cap = int(counter_offer_terms["lead_days"])

        line_items: list[dict[str, Any]] = []
        base_total = 0.0
        adjusted_total = 0.0
        for item in rfq_items:
            base_price = self.base_unit_prices.get(item.product_id, 0.0)
            if base_price <= 0:
                # Supplier doesn't carry this product (shouldn't
                # happen — we filter on ProductSupplier — but safe
                # default).
                continue
            target_price = base_price * multiplier
            if counter_offer_terms:
                cap = counter_offer_terms.get(str(item.product_id))
                if cap is not None:
                    target_price = min(target_price, float(cap))
            line_items.append({
                "product_id": str(item.product_id),
                "quantity": int(item.quantity),
                "unit_price": round(target_price, 4),
            })
            base_total += float(base_price) * int(item.quantity)
            adjusted_total += target_price * int(item.quantity)

        lead_time = max(MIN_LEAD_DAYS, self.base_lead_days + lead_delta)
        if co_lead_cap is not None:
            lead_time = max(MIN_LEAD_DAYS, min(lead_time, co_lead_cap))

        return Bid(
            supplier_id=self.supplier_id,
            line_items=line_items,
            lead_time_days=lead_time,
            strategy=self.strategy.value,
            base_total=round(base_total, 4),
            adjusted_total=round(adjusted_total, 4),
        )


def derive_strategy(supplier: Supplier) -> AgentStrategy:
    """Map a supplier's ratings to a strategy, deterministically.

    * Premium if ``rating_overall >= 4.5`` and ``on_time_pct >= 95``.
    * Slow-but-cheap if ``on_time_pct < 88``.
    * Otherwise, a deterministic 50/50 between balanced and aggressive
      (based on the hash of the supplier's email so the split is stable
      across runs).
    """
    if supplier.rating_overall >= 4.5 and supplier.on_time_pct >= 95.0:
        return AgentStrategy.PREMIUM
    if supplier.on_time_pct < 88.0:
        return AgentStrategy.SLOW_BUT_CHEAP
    return AgentStrategy.AGGRESSIVE if hash(supplier.contact_email) % 2 else AgentStrategy.BALANCED


async def _eligible_suppliers(
    db: AsyncSession,
    rfq: RFQ,
) -> list[Supplier]:
    """Suppliers that serve the RFQ's port, are active, and have at
    least one ProductSupplier row covering the RFQ's items in stock.

    Also filters out suppliers that already have a real (non-sim)
    SupplierQuote on this RFQ — there's a UniqueConstraint on
    (rfq_id, supplier_id) and we don't want to fight it.
    """
    product_ids = {item.product_id for item in rfq.items}
    if not product_ids:
        return []
    rows = (await db.execute(
        select(Supplier, SupplierPort, ProductSupplier)
        .join(SupplierPort, SupplierPort.supplier_id == Supplier.id)
        .join(ProductSupplier, ProductSupplier.supplier_id == Supplier.id)
        .where(
            SupplierPort.port_id == rfq.port_id,
            Supplier.status == SupplierStatus.ACTIVE,
            ProductSupplier.product_id.in_(product_ids),
            ProductSupplier.in_stock.is_(True),
        )
    )).all()
    # Build the set: keep suppliers that have all required products
    by_supplier: dict[UUID, tuple[Supplier, set[UUID]]] = {}
    for s, _sp, ps in rows:
        if s.id not in by_supplier:
            by_supplier[s.id] = (s, set())
        by_supplier[s.id][1].add(ps.product_id)
    eligible = [
        s for s, products in by_supplier.values() if product_ids.issubset(products)
    ]
    # Filter out suppliers with existing real (non-sim) quotes
    real_quote_rows = (await db.execute(
        select(SupplierQuote.supplier_id).where(
            SupplierQuote.rfq_id == rfq.id,
            SupplierQuote.source != "sim",
        )
    )).scalars().all()
    real_quote_supplier_ids = set(real_quote_rows)
    return [s for s in eligible if s.id not in real_quote_supplier_ids]


async def _build_agents(
    db: AsyncSession,
    rfq: RFQ,
    suppliers: list[Supplier],
    run_seed: int,
) -> list[SupplierAgent]:
    """Construct one SupplierAgent per supplier, with base prices
    cached from ProductSupplier.
    """
    product_ids = [item.product_id for item in rfq.items]
    sp_rows = (await db.execute(
        select(ProductSupplier).where(
            ProductSupplier.supplier_id.in_([s.id for s in suppliers]),
            ProductSupplier.product_id.in_(product_ids),
        )
    )).scalars().all()
    prices_by_supplier: dict[UUID, dict[UUID, float]] = {}
    lead_by_supplier: dict[UUID, list[int]] = {}
    for ps in sp_rows:
        prices_by_supplier.setdefault(ps.supplier_id, {})[ps.product_id] = float(ps.unit_price)
        lead_by_supplier.setdefault(ps.supplier_id, []).append(int(ps.lead_time_days))

    agents: list[SupplierAgent] = []
    for s in suppliers:
        product_prices = prices_by_supplier.get(s.id, {})
        if not product_prices:
            continue
        lead_times = lead_by_supplier.get(s.id, [7])
        agents.append(SupplierAgent(
            supplier_id=s.id,
            supplier_name=s.company_name,
            rating_reliability=float(s.rating_reliability or 0.0),
            rating_quality=float(s.rating_quality or 0.0),
            on_time_pct=float(s.on_time_pct or 0.0),
            avg_response_hours=float(s.avg_response_hours or 0.0),
            currency=s.currency or "USD",
            base_unit_prices=product_prices,
            base_lead_days=int(sum(lead_times) / max(len(lead_times), 1)),
            rng_seed=hash((run_seed, s.id)) & 0x7FFF_FFFF,
            strategy=derive_strategy(s),
        ))
    return agents


def _seed_from_payload(
    rfq: RFQ,
    requested_seed: int,
) -> int:
    """Pick the actual seed for this run.

    Round 1: use the requested seed verbatim.
    Round 2: use ``last_sim_seed + 1`` so re-running the same counter-
    offer against the same RFQ gives the same result (the frontend's
    what-if slider only varies weights, not seeds, so the underlying
    bids stay stable).
    """
    extra = rfq.extra or {}
    if (extra.get("sim_round") or 0) >= 1:
        last = extra.get("last_sim_seed")
        if last is None:
            return int(requested_seed) + 1
        return int(last) + 1
    return int(requested_seed)


async def _persist_events(db: AsyncSession, events: list[MarketSimEvent]) -> None:
    """Bulk insert a batch of events. Caller commits."""
    if not events:
        return
    db.add_all(events)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _score_bids(
    bids: list[Bid],
    suppliers_by_id: dict[UUID, Supplier],
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Score a list of in-memory bids (no DB) and return the same
    shape as ``compare_quotes``: ``{results, winner, weights}``.

    Used in dry-run mode so we don't have to persist sim quotes
    just to score them — keeping the bid war ephemeral.
    """
    if not bids:
        return {"results": [], "winner": None, "weights": weights or {}}

    # Normalize weights (default to platform defaults if missing).
    w = dict(weights or {
        "price": 0.4, "lead_time": 0.2, "reliability": 0.2, "quality": 0.2,
    })
    total = sum(w.values()) or 1.0
    w = {k: v / total for k, v in w.items()}

    prices = [b.adjusted_total for b in bids]
    leads = [b.lead_time_days for b in bids]
    p_min, p_max = min(prices), max(prices)
    l_min, l_max = min(leads), max(leads)

    results = []
    winner_bid: Bid | None = None
    winner_score = -1.0
    for b in bids:
        supplier = suppliers_by_id.get(b.supplier_id)
        rel = float(supplier.rating_reliability or 0) if supplier else 0.0
        qual = float(supplier.rating_quality or 0) if supplier else 0.0
        price_norm = (p_max - b.adjusted_total) / max(p_max - p_min, 1e-9) if p_max > p_min else 1.0
        lead_norm = (l_max - b.lead_time_days) / max(l_max - l_min, 1e-9) if l_max > l_min else 1.0
        rel_norm = rel / 5.0
        qual_norm = qual / 5.0
        score = (
            w["price"] * price_norm
            + w["lead_time"] * lead_norm
            + w["reliability"] * rel_norm
            + w["quality"] * qual_norm
        )
        results.append({
            "supplier_id": str(b.supplier_id),
            "supplier_name": supplier.company_name if supplier else "Unknown",
            "total": round(b.adjusted_total, 4),
            "currency": supplier.currency if supplier else None,
            "lead_time_days": b.lead_time_days,
            "reliability": rel,
            "quality": qual,
            "subscores": {
                "price": round(price_norm, 4),
                "lead_time": round(lead_norm, 4),
                "reliability": round(rel_norm, 4),
                "quality": round(qual_norm, 4),
            },
            "score": round(score, 6),
        })
        if score > winner_score:
            winner_score = score
            winner_bid = b

    results.sort(key=lambda r: r["score"], reverse=True)
    return {
        "results": results,
        "winner": str(winner_bid.supplier_id) if winner_bid else None,
        "weights": w,
    }


async def run_market_sim(
    db: AsyncSession,
    rfq: RFQ,
    *,
    seed: int = 42,
    weights: dict[str, float] | None = None,
    counter_offer_terms: dict[str, Any] | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Run one marketplace sim round for the given RFQ.

    Returns a dict with ``round``, ``winner`` (or None), ``results``
    (the same payload shape as ``compare_quotes``), ``events`` (the
    audit-log rows for this run), and ``weights`` (the normalized
    weights that were used).

    If ``dry_run`` is True, the sim bids normally but does NOT
    transition the RFQ to ``awarded`` — the buyer can keep
    re-simulating. The default is dry-run so the demo "what-if
    slider" works without locking the RFQ on the first click.
    """
    now = _now()
    run_seed = _seed_from_payload(rfq, seed)
    extra = dict(rfq.extra or {})
    last_round = int(extra.get("sim_round") or 0)
    round_n = last_round + 1  # 1 for fresh, 2 for counter-offer, ...

    # The RFQ must be in a state that accepts quotes. Re-open it if
    # the previous round left it in AWARDED (only happens in
    # non-dry-run mode; in dry-run the status never moves to AWARDED).
    if rfq.status == RFQStatus.AWARDED:
        # Reset to a state that accepts new quotes (only happens in
        # non-dry-run mode; in dry-run the status never moves to AWARDED).
        rfq.status = RFQStatus.OPEN
    if rfq.status == RFQStatus.CLOSED:
        # The sim is reopening for a new round.
        rfq.status = RFQStatus.OPEN
        rfq.responded_count = 0

    # Bump invited_count so the CLOSED-threshold check in
    # submit_quote() doesn't auto-close the RFQ while we're bidding.
    # We don't actually care about invited_count during a sim; we
    # restore it at the end of the run.
    original_invited_count = rfq.invited_count
    rfq.invited_count = max(original_invited_count, 10_000)

    # 1) Load eligible suppliers.
    eligible = await _eligible_suppliers(db, rfq)
    if not eligible:
        return {
            "round": round_n,
            "winner": None,
            "results": [],
            "events": [],
            "weights": weights or {},
            "message": "No eligible suppliers for this RFQ.",
        }

    # 2) Build agents.
    agents = await _build_agents(db, rfq, eligible, run_seed)
    if not agents:
        return {
            "round": round_n,
            "winner": None,
            "results": [],
            "events": [],
            "weights": weights or {},
            "message": "Eligible suppliers have no ProductSupplier coverage.",
        }

    # 3) Decide which agents bid this round.
    if round_n == 1:
        bidding_agents = [a for a in agents if not a.dropped_out]
    else:
        # Round 2: read the round-1 results from the RFQ's quotes to
        # figure out who was "in contention". We treat "had a
        # SupplierQuote from a sim source" as a round-1 bid.
        round1_scores: dict[UUID, float] = {
            q.supplier_id: float(q.score)
            for q in rfq.quotes
            if q.source == "sim"
        }
        if not round1_scores:
            # No sim quotes from round 1 — fall back to all agents.
            bidding_agents = [a for a in agents if not a.dropped_out]
        else:
            top_score = max(round1_scores.values())
            bidding_agents = [
                a for a in agents
                if not a.dropped_out
                and round1_scores.get(a.supplier_id, 0.0) >= top_score - ROUND_2_MARGIN
            ]

    # 4) Submit one bid per bidding agent.
    rfq_items: list[RFQItem] = list(rfq.items)
    new_events: list[MarketSimEvent] = []
    new_events.append(MarketSimEvent(
        rfq_id=rfq.id,
        ts=now,
        round=round_n,
        event_type=MarketSimEventType.RUN_START.value,
        payload={"seed": run_seed, "dry_run": dry_run, "agents": len(agents), "bidders": len(bidding_agents)},
    ))
    if counter_offer_terms:
        new_events.append(MarketSimEvent(
            rfq_id=rfq.id,
            ts=now,
            round=round_n,
            event_type=MarketSimEventType.COUNTER_OFFER.value,
            payload=counter_offer_terms,
        ))

    submitted_quote_ids: list[UUID] = []
    bids: list[Bid] = []
    suppliers_by_id = {s.id: s for s in eligible}
    for agent in bidding_agents:
        bid = agent.generate_bid(
            rfq_id=rfq.id,
            round_n=round_n,
            rfq_items=rfq_items,
            counter_offer_terms=counter_offer_terms,
        )
        bids.append(bid)
        supplier_obj = suppliers_by_id.get(agent.supplier_id)
        if supplier_obj is None:
            continue
        if dry_run:
            # Dry-run: don't persist SupplierQuote rows. The bid stays
            # in memory; we score via _score_bids. This keeps the bid
            # war ephemeral and avoids UniqueConstraint conflicts on
            # round 2 (the user can re-simulate the same RFQ).
            new_events.append(MarketSimEvent(
                rfq_id=rfq.id, ts=_now(), round=round_n,
                event_type=MarketSimEventType.BID_ARRIVED.value,
                supplier_id=agent.supplier_id,
                payload={**bid.as_payload(), "quote_id": None},
            ))
            continue
        try:
            quote = await submit_quote(
                db, rfq, supplier_obj,
                line_items=bid.line_items,
                lead_time_days=bid.lead_time_days,
                payment_terms=None,
                notes=f"Simulated bid (strategy={agent.strategy.value}, round={round_n})",
                source="sim",
            )
            quote.supplier = supplier_obj
            rfq.quotes.append(quote)
            await db.flush()
            submitted_quote_ids.append(quote.id)
        except Exception as exc:  # pragma: no cover - defensive
            new_events.append(MarketSimEvent(
                rfq_id=rfq.id, ts=_now(), round=round_n,
                event_type=MarketSimEventType.BID_ARRIVED.value,
                supplier_id=agent.supplier_id,
                payload={"error": str(exc), "strategy": agent.strategy.value},
            ))
            continue
        new_events.append(MarketSimEvent(
            rfq_id=rfq.id, ts=_now(), round=round_n,
            event_type=MarketSimEventType.BID_ARRIVED.value,
            supplier_id=agent.supplier_id,
            payload={**bid.as_payload(), "quote_id": str(quote.id)},
        ))

    # 5) Score the round.
    if dry_run:
        # In-memory scoring — no DB writes, no awarded state mutation.
        comparison = _score_bids(bids, suppliers_by_id, weights=weights)
    else:
        comparison = await compare_quotes(
            db, rfq, weights=weights, save=True,
        )

    new_events.append(MarketSimEvent(
        rfq_id=rfq.id,
        ts=_now(),
        round=round_n,
        event_type=MarketSimEventType.ROUND_CLOSE.value,
        payload={
            "weights": comparison.get("weights") or {},
            "winner_supplier_id": comparison.get("winner"),
            "winner_quote_id": comparison.get("winner_quote_id"),
            "results": comparison.get("results") or [],
        },
    ))
    new_events.append(MarketSimEvent(
        rfq_id=rfq.id,
        ts=_now(),
        round=round_n,
        event_type=MarketSimEventType.RUN_END.value,
        payload={"round": round_n, "bids": len(bids)},
    ))

    await _persist_events(db, new_events)

    # Restore invited_count so the production flow isn't disturbed.
    rfq.invited_count = original_invited_count

    # Track the round + last seed on rfq.extra so the next call knows
    # whether it's a counter-offer (round 2) or a fresh run.
    rfq.extra = {
        **(rfq.extra or {}),
        "sim_round": round_n,
        "last_sim_seed": run_seed,
    }

    return {
        "round": round_n,
        "winner": comparison.get("winner"),
        "results": comparison.get("results") or [],
        "events": [
            {
                "id": str(e.id),
                "ts": e.ts.isoformat(),
                "round": e.round,
                "event_type": e.event_type,
                "supplier_id": str(e.supplier_id) if e.supplier_id else None,
                "payload": e.payload,
            }
            for e in new_events
        ],
        "weights": comparison.get("weights") or weights or {},
        "dry_run": dry_run,
    }


__all__ = [
    "AgentStrategy",
    "Bid",
    "SupplierAgent",
    "STRATEGY_PARAMS",
    "ROUND_2_MARGIN",
    "derive_strategy",
    "run_market_sim",
]

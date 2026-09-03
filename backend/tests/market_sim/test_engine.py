"""Tests for the run_market_sim engine.

These tests focus on the parts of the engine that don't require a real
PostgreSQL session: the seed-pickup helper, the round-2 re-bid selection
rule, and the deterministic structure of the bid payload. The full
end-to-end flow (submit_quote + compare_quotes against a real DB) is
covered by the route test in tests/api/test_market_sim.py.
"""
from __future__ import annotations

import random
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.market_sim import (
    ROUND_2_MARGIN,
    STRATEGY_PARAMS,
    AgentStrategy,
    Bid,
    SupplierAgent,
    derive_strategy,
    _seed_from_payload,
)


# --- _seed_from_payload ------------------------------------------------


class TestSeedFromPayload:
    def test_fresh_run_uses_requested_seed(self) -> None:
        rfq = SimpleNamespace(extra={})
        assert _seed_from_payload(rfq, 42) == 42

    def test_fresh_run_with_no_extra_uses_requested(self) -> None:
        rfq = SimpleNamespace(extra=None)
        assert _seed_from_payload(rfq, 7) == 7

    def test_round_2_increments_last_seed(self) -> None:
        rfq = SimpleNamespace(extra={"sim_round": 1, "last_sim_seed": 42})
        assert _seed_from_payload(rfq, 99) == 43

    def test_round_2_falls_back_to_requested_when_no_last_seed(self) -> None:
        rfq = SimpleNamespace(extra={"sim_round": 1, "last_sim_seed": None})
        # requested_seed + 1
        assert _seed_from_payload(rfq, 50) == 51

    def test_does_not_mutate_rfq_extra(self) -> None:
        extra = {"sim_round": 1, "last_sim_seed": 42}
        rfq = SimpleNamespace(extra=extra)
        _seed_from_payload(rfq, 99)
        assert rfq.extra == extra


# --- round-2 selection rule -------------------------------------------


class TestRound2Selection:
    """The "in-contention" rule: only agents within ROUND_2_MARGIN of
    the round-1 winner's score re-bid in round 2."""

    def test_margin_constant_is_small(self) -> None:
        # Sanity: if the margin ever drifts above 0.20 the demo's
        # "round 2 narrows the field" effect breaks.
        assert 0.0 < ROUND_2_MARGIN <= 0.20

    def test_only_top_agents_rebid(self) -> None:
        # Three agents, round-1 scores: 0.90, 0.50, 0.10. With
        # ROUND_2_MARGIN=0.05, only the winner (0.90) re-bids.
        round1_scores = {uuid4(): 0.90, uuid4(): 0.50, uuid4(): 0.10}
        top = max(round1_scores.values())
        in_contention = [
            sid for sid, score in round1_scores.items()
            if score >= top - ROUND_2_MARGIN
        ]
        assert len(in_contention) == 1
        assert list(round1_scores.keys())[0] in in_contention

    def test_tied_scores_all_rebid(self) -> None:
        # Two agents tied — both should re-bid.
        a, b = uuid4(), uuid4()
        round1_scores = {a: 0.75, b: 0.75}
        top = max(round1_scores.values())
        in_contention = [
            sid for sid, score in round1_scores.items()
            if score >= top - ROUND_2_MARGIN
        ]
        assert set(in_contention) == {a, b}

    def test_within_margin_rebids(self) -> None:
        # Two agents, gap 0.03 < margin 0.05 → both re-bid.
        a, b = uuid4(), uuid4()
        round1_scores = {a: 0.80, b: 0.77}
        top = max(round1_scores.values())
        in_contention = [
            sid for sid, score in round1_scores.items()
            if score >= top - ROUND_2_MARGIN
        ]
        assert set(in_contention) == {a, b}


# --- Bid payload structure --------------------------------------------


class TestBidPayload:
    def _agent(self, strategy: AgentStrategy) -> SupplierAgent:
        # Return (agent, product_id) so tests can build a matching item.
        pid = uuid4()
        return (
            SupplierAgent(
                supplier_id=uuid4(),
                supplier_name=f"Supplier {strategy.value}",
                rating_reliability=4.0,
                rating_quality=4.0,
                on_time_pct=92.0,
                avg_response_hours=12.0,
                currency="USD",
                base_unit_prices={pid: 100.0},
                base_lead_days=7,
                rng_seed=42,
                strategy=strategy,
            ),
            pid,
        )

    def test_payload_carries_required_keys(self) -> None:
        from types import SimpleNamespace
        rfq = SimpleNamespace(id=uuid4())
        agent, pid = self._agent(AgentStrategy.BALANCED)
        item = SimpleNamespace(product_id=pid, quantity=2)
        bid = agent.generate_bid(rfq_id=rfq.id, round_n=1, rfq_items=[item])
        payload = bid.as_payload()
        assert "supplier_id" in payload
        assert "lead_time_days" in payload
        assert "strategy" in payload
        assert "base_total" in payload
        assert "adjusted_total" in payload
        assert "line_items" in payload
        assert payload["strategy"] == "balanced"
        assert payload["base_total"] == 200.0
        # 2 × unit_price. base=100, balanced mult = 1 + (-0.05 + jitter).
        # So adjusted_total ∈ [190.0, 194.0] (qty=2).
        assert 190.0 <= payload["adjusted_total"] <= 194.0

    def test_payload_line_items_have_unit_price(self) -> None:
        from types import SimpleNamespace
        rfq = SimpleNamespace(id=uuid4())
        agent, pid = self._agent(AgentStrategy.AGGRESSIVE)
        item = SimpleNamespace(product_id=pid, quantity=1)
        bid = agent.generate_bid(rfq_id=rfq.id, round_n=1, rfq_items=[item])
        assert len(bid.line_items) == 1
        li = bid.line_items[0]
        assert li["product_id"] == str(pid)
        assert li["quantity"] == 1
        assert isinstance(li["unit_price"], float)


# --- strategy parameter sanity ----------------------------------------


class TestStrategyParams:
    """The four strategies are characterized by their price/lead
    deltas. If anyone tweaks STRATEGY_PARAMS, the demo's "premium is
    expensive, slow_but_cheap is cheapest" narrative breaks."""

    def test_premium_is_most_expensive(self) -> None:
        mults = [v[0] for v in STRATEGY_PARAMS.values()]
        assert STRATEGY_PARAMS["premium"][0] == max(mults)

    def test_slow_but_cheap_is_cheapest(self) -> None:
        mults = [v[0] for v in STRATEGY_PARAMS.values()]
        assert STRATEGY_PARAMS["slow_but_cheap"][0] == min(mults)

    def test_premium_is_slower_than_balanced(self) -> None:
        assert STRATEGY_PARAMS["premium"][1] > STRATEGY_PARAMS["balanced"][1]

    def test_aggressive_is_faster_than_balanced(self) -> None:
        assert STRATEGY_PARAMS["aggressive"][1] < STRATEGY_PARAMS["balanced"][1]

    def test_slow_but_cheap_is_slowest(self) -> None:
        leads = [v[1] for v in STRATEGY_PARAMS.values()]
        assert STRATEGY_PARAMS["slow_but_cheap"][1] == max(leads)


# --- derive_strategy coverage -----------------------------------------


class TestDeriveStrategyCoverage:
    """Make sure every strategy is reachable from some rating
    combination — protects against an accidental \"all balanced\"
    regression that would make the bid war boring."""

    def test_all_four_strategies_reachable(self) -> None:
        seen: set[AgentStrategy] = set()
        for rating in (3.5, 4.0, 4.7):
            for on_time in (80.0, 88.0, 92.0, 96.0):
                from app.models.supplier import Supplier, SupplierStatus
                s = Supplier(
                    id=uuid4(),
                    company_name="x",
                    contact_email=f"r{rating}-o{on_time}@x.com",
                    status=SupplierStatus.ACTIVE,
                    rating_overall=rating,
                    on_time_pct=on_time,
                )
                seen.add(derive_strategy(s))
        assert seen == set(AgentStrategy)

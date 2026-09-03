"""Tests for the SupplierAgent and the strategy math.

These tests don't need a database — they exercise the pure-Python
``SupplierAgent.generate_bid`` math, the ``derive_strategy`` mapping,
and the per-supplier RNG determinism.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from app.services.market_sim import (
    AgentStrategy,
    Bid,
    STRATEGY_PARAMS,
    SupplierAgent,
    derive_strategy,
)
from app.models.supplier import Supplier, SupplierStatus


# --- helpers ----------------------------------------------------------


def _make_supplier(
    *,
    rating_overall: float = 4.0,
    on_time_pct: float = 92.0,
    email: str = "supplier@example.com",
):
    """Build a minimal Supplier-like object for derive_strategy."""
    s = Supplier(
        id=uuid4(),
        company_name="Test Supplier",
        contact_email=email,
        status=SupplierStatus.ACTIVE,
        rating_overall=rating_overall,
        on_time_pct=on_time_pct,
    )
    return s


def _make_agent(strategy: AgentStrategy, *, product_prices=None) -> SupplierAgent:
    return SupplierAgent(
        supplier_id=uuid4(),
        supplier_name="Test Supplier",
        rating_reliability=4.0,
        rating_quality=4.0,
        on_time_pct=92.0,
        avg_response_hours=12.0,
        currency="USD",
        base_unit_prices=product_prices or _DEFAULT_PRICES(),
        base_lead_days=7,
        rng_seed=42,
        strategy=strategy,
    )


# Stable product ids so tests can build matching rfq_items without
# threading UUIDs through every call site.
_PRODUCT_ID_A = uuid4()
_PRODUCT_ID_B = uuid4()


def _DEFAULT_PRICES() -> dict:
    return {_PRODUCT_ID_A: 100.0, _PRODUCT_ID_B: 50.0}


# --- derive_strategy --------------------------------------------------


class TestDeriveStrategy:
    def test_premium_high_overall_and_on_time(self) -> None:
        s = _make_supplier(rating_overall=4.7, on_time_pct=96.0)
        assert derive_strategy(s) == AgentStrategy.PREMIUM

    def test_slow_but_cheap_low_on_time(self) -> None:
        s = _make_supplier(rating_overall=4.0, on_time_pct=85.0)
        assert derive_strategy(s) == AgentStrategy.SLOW_BUT_CHEAP

    def test_otherwise_balanced_or_aggressive(self) -> None:
        # rating_overall=4.0, on_time_pct=92.0 — falls into the
        # "balanced/aggressive" branch.
        s = _make_supplier(rating_overall=4.0, on_time_pct=92.0)
        strat = derive_strategy(s)
        assert strat in (AgentStrategy.BALANCED, AgentStrategy.AGGRESSIVE)

    def test_strategy_deterministic_for_same_email(self) -> None:
        s1 = _make_supplier(email="alpha@example.com")
        s2 = _make_supplier(email="alpha@example.com")
        assert derive_strategy(s1) == derive_strategy(s2)

    def test_strategy_different_for_different_emails(self) -> None:
        # Hash mod 2 splits — at least one of these pairs must differ
        # across the 4 suppliers we test.
        seen = {
            derive_strategy(_make_supplier(email=f"a{i}@example.com")).value
            for i in range(20)
        }
        # We should see both balanced and aggressive in there.
        assert {"balanced", "aggressive"}.issubset(seen)


# --- SupplierAgent.generate_bid ---------------------------------------


class TestGenerateBid:
    def test_aggressive_below_baseline(self) -> None:
        from types import SimpleNamespace
        rfq = SimpleNamespace(id=uuid4())
        item = SimpleNamespace(
            product_id=_PRODUCT_ID_A,
            quantity=1,
        )
        agent = _make_agent(AgentStrategy.AGGRESSIVE)
        bid = agent.generate_bid(rfq_id=rfq.id, round_n=1, rfq_items=[item])
        # base = 100, aggressive mult = 1 + (-0.10 + jitter). min ~ 0.88 * 100 = 88, max ~ 0.92 * 100 = 92
        assert bid.adjusted_total < 100.0
        assert bid.adjusted_total >= 88.0
        assert bid.lead_time_days == 5  # 7 + (-2) = 5

    def test_premium_above_baseline(self) -> None:
        from types import SimpleNamespace
        rfq = SimpleNamespace(id=uuid4())
        item = SimpleNamespace(
            product_id=_PRODUCT_ID_A,
            quantity=1,
        )
        agent = _make_agent(AgentStrategy.PREMIUM)
        bid = agent.generate_bid(rfq_id=rfq.id, round_n=1, rfq_items=[item])
        # premium mult = 1 + (0.08 + jitter). min ~ 1.06 * 100 = 106, max ~ 1.10 * 100 = 110
        assert bid.adjusted_total > 100.0
        assert bid.adjusted_total <= 110.0
        assert bid.lead_time_days == 10  # 7 + 3

    def test_slow_but_cheap_cheapest_and_slowest(self) -> None:
        from types import SimpleNamespace
        rfq = SimpleNamespace(id=uuid4())
        item = SimpleNamespace(
            product_id=_PRODUCT_ID_A,
            quantity=1,
        )
        agent = _make_agent(AgentStrategy.SLOW_BUT_CHEAP)
        bid = agent.generate_bid(rfq_id=rfq.id, round_n=1, rfq_items=[item])
        # slow_but_cheap mult = 1 + (-0.18 + jitter). min ~ 0.80 * 100 = 80
        assert bid.adjusted_total < 90.0
        assert bid.lead_time_days == 14  # 7 + 7

    def test_deterministic_given_seed(self) -> None:
        from types import SimpleNamespace
        rfq = SimpleNamespace(id=uuid4())
        item = SimpleNamespace(
            product_id=_PRODUCT_ID_A,
            quantity=1,
        )
        agent = _make_agent(AgentStrategy.AGGRESSIVE)
        bid1 = agent.generate_bid(rfq_id=rfq.id, round_n=1, rfq_items=[item])
        bid2 = agent.generate_bid(rfq_id=rfq.id, round_n=1, rfq_items=[item])
        assert bid1.adjusted_total == bid2.adjusted_total
        assert bid1.lead_time_days == bid2.lead_time_days

    def test_different_round_produces_different_bid(self) -> None:
        from types import SimpleNamespace
        rfq = SimpleNamespace(id=uuid4())
        item = SimpleNamespace(
            product_id=_PRODUCT_ID_A,
            quantity=1,
        )
        agent = _make_agent(AgentStrategy.BALANCED)
        bid1 = agent.generate_bid(rfq_id=rfq.id, round_n=1, rfq_items=[item])
        bid2 = agent.generate_bid(rfq_id=rfq.id, round_n=2, rfq_items=[item])
        # The round index is part of the seed, so the jitter differs.
        assert bid1.adjusted_total != bid2.adjusted_total

    def test_counter_offer_caps_price(self) -> None:
        from types import SimpleNamespace
        rfq = SimpleNamespace(id=uuid4())
        item = SimpleNamespace(product_id=_PRODUCT_ID_A, quantity=1)
        agent = _make_agent(AgentStrategy.AGGRESSIVE)
        # Cap the price at 80 — should force the bid to that.
        bid = agent.generate_bid(
            rfq_id=rfq.id,
            round_n=2,
            rfq_items=[item],
            counter_offer_terms={str(_PRODUCT_ID_A): 80.0},
        )
        assert bid.adjusted_total == 80.0

    def test_counter_offer_caps_lead_time(self) -> None:
        from types import SimpleNamespace
        rfq = SimpleNamespace(id=uuid4())
        item = SimpleNamespace(
            product_id=_PRODUCT_ID_A,
            quantity=1,
        )
        agent = _make_agent(AgentStrategy.PREMIUM)
        # Premium lead = 10 days. Cap at 4 → should be 4.
        bid = agent.generate_bid(
            rfq_id=rfq.id,
            round_n=2,
            rfq_items=[item],
            counter_offer_terms={"lead_days": 4},
        )
        assert bid.lead_time_days == 4

    def test_lead_time_floor_at_min(self) -> None:
        from types import SimpleNamespace
        rfq = SimpleNamespace(id=uuid4())
        item = SimpleNamespace(
            product_id=_PRODUCT_ID_A,
            quantity=1,
        )
        agent = _make_agent(AgentStrategy.AGGRESSIVE)
        agent.base_lead_days = 1
        bid = agent.generate_bid(rfq_id=rfq.id, round_n=1, rfq_items=[item])
        # aggressive = -2 days → would go to -1, floored at 1.
        assert bid.lead_time_days == 1

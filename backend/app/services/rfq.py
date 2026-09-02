"""
Dynamic Supplier Bidding service.

Workflow:
1. Order is created and a supplier is required.
2. We build an RFQ targeting suppliers that serve the destination port.
3. Suppliers respond with quotes (manually or via API).
4. We score each quote: weighted sum of price (lower better), lead time
   (lower better), reliability (higher better), quality (higher better).
5. We pick the winner; losers are marked.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.order import Order, OrderItem, OrderStatus
from app.models.supplier import ProductSupplier
from app.models.supplier import (
    BidComparison,
    RFQ,
    RFQItem,
    RFQStatus,
    Supplier,
    SupplierPort,
    SupplierQuote,
    SupplierStatus,
    QuoteItem,
)


def _new_reference(prefix: str) -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"


async def build_rfq_for_order(
    db: AsyncSession,
    order: Order,
    *,
    response_deadline_hours: int | None = None,
) -> RFQ:
    """Create an RFQ, send to all eligible suppliers at the destination port."""
    if order.status not in (OrderStatus.DRAFT, OrderStatus.PENDING_APPROVAL, OrderStatus.RFQ_IN_PROGRESS):
        raise ValueError(f"Order is in status {order.status}; cannot start RFQ")

    deadline_h = response_deadline_hours or settings.RFQ_RESPONSE_TIMEOUT_HOURS
    rfq = RFQ(
        reference=_new_reference("RFQ"),
        order_id=order.id,
        port_id=order.port_id,
        status=RFQStatus.DRAFT,
        response_deadline=datetime.now(timezone.utc) + timedelta(hours=deadline_h),
    )
    # Copy line items
    for oi in order.items:
        rfq.items.append(RFQItem(
            product_id=oi.product_id,
            quantity=oi.quantity,
            unit=oi.unit,
            target_unit_price=oi.unit_price,
        ))

    # Find eligible suppliers at this port with these products
    product_ids = {oi.product_id for oi in order.items}
    sp_rows = (await db.execute(
        select(SupplierPort, Supplier, ProductSupplier)
        .join(Supplier, Supplier.id == SupplierPort.supplier_id)
        .join(ProductSupplier, ProductSupplier.supplier_id == Supplier.id)
        .where(
            SupplierPort.port_id == order.port_id,
            Supplier.status == SupplierStatus.ACTIVE,
            ProductSupplier.product_id.in_(product_ids),
            ProductSupplier.in_stock.is_(True),
        )
    )).all()
    # Build a unique supplier set
    supplier_ids = {s.id for _, s, _ in sp_rows}
    rfq.invited_count = len(supplier_ids)

    db.add(rfq)
    await db.flush()  # need rfq.id

    # Mark as sent + schedule notifications
    rfq.status = RFQStatus.SENT
    rfq.sent_at = datetime.now(timezone.utc)
    rfq.extra = {
        "invited_supplier_ids": [str(s) for s in supplier_ids],
        # In production: hand off to Celery to email / push to API
        "notification_jobs": "queued",
    }
    order.status = OrderStatus.RFQ_IN_PROGRESS

    return rfq


async def compare_quotes(
    db: AsyncSession,
    rfq: RFQ,
    weights: dict[str, float] | None = None,
    *,
    save: bool = True,
) -> dict[str, Any]:
    """Score each quote and pick a winner.

    The score is a weighted sum of four normalized sub-scores (each in [0, 1]).
    """
    weights = weights or {
        "price": settings.SUPPLIER_SCORE_WEIGHT_PRICE,
        "lead_time": settings.SUPPLIER_SCORE_WEIGHT_LEAD_TIME,
        "reliability": settings.SUPPLIER_SCORE_WEIGHT_RELIABILITY,
        "quality": settings.SUPPLIER_SCORE_WEIGHT_QUALITY,
    }
    total_w = sum(weights.values())
    if total_w <= 0:
        raise ValueError("weights must sum to > 0")
    weights = {k: v / total_w for k, v in weights.items()}

    quotes = rfq.quotes
    if not quotes:
        return {"results": [], "winner": None}

    # Compute normalization bounds
    prices = [float(q.total) for q in quotes]
    leads = [q.lead_time_days for q in quotes]
    rels = [q.supplier.rating_reliability for q in quotes]
    quals = [q.supplier.rating_quality for q in quotes]
    p_min, p_max = min(prices), max(prices)
    l_min, l_max = min(leads), max(leads)

    results = []
    winner = None
    winner_score = -1.0
    for q in quotes:
        # Lower is better -> invert (1 - normalized)
        price_norm = (p_max - float(q.total)) / max(p_max - p_min, 1e-9) if p_max > p_min else 1.0
        lead_norm = (l_max - q.lead_time_days) / max(l_max - l_min, 1e-9) if l_max > l_min else 1.0
        rel_norm = (q.supplier.rating_reliability or 0) / 5.0
        qual_norm = (q.supplier.rating_quality or 0) / 5.0
        score = (
            weights["price"] * price_norm
            + weights["lead_time"] * lead_norm
            + weights["reliability"] * rel_norm
            + weights["quality"] * qual_norm
        )
        q.score = round(score, 6)
        result = {
            "quote_id": str(q.id),
            "supplier_id": str(q.supplier_id),
            "supplier_name": q.supplier.company_name,
            "total": float(q.total),
            "currency": q.currency,
            "lead_time_days": q.lead_time_days,
            "reliability": q.supplier.rating_reliability,
            "quality": q.supplier.rating_quality,
            "subscores": {
                "price": round(price_norm, 4),
                "lead_time": round(lead_norm, 4),
                "reliability": round(rel_norm, 4),
                "quality": round(qual_norm, 4),
            },
            "score": round(score, 6),
        }
        results.append(result)
        if score > winner_score:
            winner_score = score
            winner = q

    results.sort(key=lambda r: r["score"], reverse=True)
    if winner is not None:
        for q in quotes:
            q.is_awarded = q.id == winner.id
        rfq.status = RFQStatus.AWARDED
        rfq.awarded_at = datetime.now(timezone.utc)
        rfq.awarded_quote_id = winner.id
        rfq.responded_count = len([q for q in quotes if not q.is_rejected])
        winner.order_id = rfq.order_id

    if save:
        db.add(BidComparison(
            rfq_id=rfq.id,
            weights=weights,
            results=results,
            winner_quote_id=winner.id if winner else None,
        ))

    return {"results": results, "winner": str(winner.id) if winner else None}


async def submit_quote(
    db: AsyncSession,
    rfq: RFQ,
    supplier: Supplier,
    *,
    line_items: list[dict[str, Any]],
    lead_time_days: int,
    payment_terms: str | None = None,
    notes: str | None = None,
    source: str = "portal",
) -> SupplierQuote:
    """Supplier submits a quote for an RFQ."""
    if rfq.status not in (RFQStatus.SENT, RFQStatus.OPEN):
        raise ValueError(f"RFQ is {rfq.status}; cannot accept quotes")
    if datetime.now(timezone.utc) > rfq.response_deadline:
        raise ValueError("RFQ response deadline passed")

    subtotal = 0.0
    quote_items: list[QuoteItem] = []
    for li in line_items:
        product_id = li["product_id"]
        qty = int(li["quantity"])
        unit_price = float(li["unit_price"])
        line_total = round(qty * unit_price, 4)
        subtotal += line_total
        quote_items.append(QuoteItem(
            product_id=product_id,
            quantity=qty,
            unit_price=unit_price,
            line_total=line_total,
        ))

    quote = SupplierQuote(
        rfq_id=rfq.id,
        supplier_id=supplier.id,
        order_id=rfq.order_id,
        reference=_new_reference("Q"),
        subtotal=round(subtotal, 4),
        tax=0,
        shipping=0,
        total=round(subtotal, 4),
        lead_time_days=lead_time_days,
        payment_terms=payment_terms,
        notes=notes,
        source=source,
        valid_until=datetime.now(timezone.utc) + timedelta(days=14),
        items=quote_items,
    )
    rfq.responded_count += 1
    if rfq.responded_count >= rfq.invited_count:
        rfq.status = RFQStatus.CLOSED
    db.add(quote)
    return quote

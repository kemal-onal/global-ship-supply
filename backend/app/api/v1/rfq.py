"""RFQ & Bidding routes — create RFQ, list quotes, compare, choose winner."""
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.deps.auth import CurrentToken, DBSession, ReadDBSession
from app.models.audit import AuditAction, AuditLog
from app.models.order import Order
from app.models.supplier import (
    RFQ,
    RFQItem,
    RFQStatus,
    Supplier,
    SupplierQuote,
    SupplierStatus,
)
from app.services.market_sim import run_market_sim
from app.services.rfq import build_rfq_for_order, compare_quotes, submit_quote

router = APIRouter()


class QuoteLineIn(BaseModel):
    product_id: str
    quantity: int = Field(gt=0)
    unit_price: float = Field(ge=0)


class QuoteIn(BaseModel):
    rfq_id: str
    supplier_id: str
    lead_time_days: int = Field(ge=1, le=180)
    payment_terms: Optional[str] = None
    notes: Optional[str] = None
    source: str = "portal"
    line_items: list[QuoteLineIn]


class CompareIn(BaseModel):
    weights: dict[str, float] | None = None
    save: bool = True


@router.get("")
async def list_rfqs(
    db: ReadDBSession,
    token: CurrentToken,
    order_id: str | None = None,
    status: RFQStatus | None = None,
    limit: int = 50,
    offset: int = 0,
):
    stmt = (
        select(RFQ)
        .options(selectinload(RFQ.order), selectinload(RFQ.items))
        .order_by(RFQ.created_at.desc())
    )
    if order_id:
        stmt = stmt.where(RFQ.order_id == order_id)
    if status:
        stmt = stmt.where(RFQ.status == status)
    stmt = stmt.limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(r.id),
            "reference": r.reference,
            "order_id": str(r.order_id),
            "order_reference": r.order.reference if r.order else None,
            "port_id": str(r.port_id),
            "status": r.status.value,
            "sent_at": r.sent_at.isoformat() if r.sent_at else None,
            "response_deadline": r.response_deadline.isoformat(),
            "closed_at": r.closed_at.isoformat() if r.closed_at else None,
            "awarded_at": r.awarded_at.isoformat() if r.awarded_at else None,
            "awarded_quote_id": str(r.awarded_quote_id) if r.awarded_quote_id else None,
            "invited_count": r.invited_count,
            "responded_count": r.responded_count,
            "items": [
                {
                    "product_id": str(i.product_id),
                    "quantity": i.quantity,
                    "unit": i.unit,
                    "target_unit_price": float(i.target_unit_price) if i.target_unit_price else None,
                }
                for i in r.items
            ],
        }
        for r in rows
    ]


@router.post("/for-order/{order_id}")
async def create_rfq(
    order_id: str,
    db: DBSession,
    token: CurrentToken,
    response_deadline_hours: int | None = None,
):
    order = (await db.execute(select(Order).where(Order.id == order_id))).scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    rfq = await build_rfq_for_order(db, order, response_deadline_hours=response_deadline_hours)
    db.add(AuditLog(
        user_id=token.sub,
        action=AuditAction.RFQ_SENT,
        resource="rfqs",
        resource_id=str(rfq.id),
        description=f"RFQ {rfq.reference} sent to {rfq.invited_count} suppliers",
    ))
    await db.commit()
    return {
        "id": str(rfq.id),
        "reference": rfq.reference,
        "status": rfq.status.value,
        "invited_count": rfq.invited_count,
        "response_deadline": rfq.response_deadline.isoformat(),
    }


@router.get("/{rfq_id}")
async def get_rfq(
    rfq_id: str,
    db: ReadDBSession,
    token: CurrentToken,
):
    rfq = (
        await db.execute(
            select(RFQ)
            .options(
                selectinload(RFQ.items),
                selectinload(RFQ.quotes).selectinload(SupplierQuote.supplier),
            )
            .where(RFQ.id == rfq_id)
        )
    ).scalar_one_or_none()
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found")
    return {
        "id": str(rfq.id),
        "reference": rfq.reference,
        "order_id": str(rfq.order_id),
        "port_id": str(rfq.port_id),
        "status": rfq.status.value,
        "invited_count": rfq.invited_count,
        "responded_count": rfq.responded_count,
        "response_deadline": rfq.response_deadline.isoformat(),
        "items": [
            {
                "product_id": str(i.product_id),
                "quantity": i.quantity,
                "unit": i.unit,
                "target_unit_price": float(i.target_unit_price) if i.target_unit_price else None,
            }
            for i in rfq.items
        ],
        "quotes": [
            {
                "id": str(q.id),
                "supplier_id": str(q.supplier_id),
                "supplier_name": q.supplier.company_name,
                "reference": q.reference,
                "total": float(q.total),
                "currency": q.currency,
                "lead_time_days": q.lead_time_days,
                "score": q.score,
                "is_awarded": q.is_awarded,
                "submitted_at": q.submitted_at.isoformat(),
            }
            for q in rfq.quotes
        ],
    }


@router.post("/quotes")
async def submit_quote_route(
    payload: QuoteIn,
    db: DBSession,
    token: CurrentToken,
):
    rfq = (await db.execute(select(RFQ).where(RFQ.id == payload.rfq_id))).scalar_one_or_none()
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found")
    supplier = (await db.execute(select(Supplier).where(Supplier.id == payload.supplier_id))).scalar_one_or_none()
    if not supplier or supplier.status != SupplierStatus.ACTIVE:
        raise HTTPException(status_code=400, detail="Supplier not active")
    quote = await submit_quote(
        db, rfq, supplier,
        line_items=[li.model_dump() for li in payload.line_items],
        lead_time_days=payload.lead_time_days,
        payment_terms=payload.payment_terms,
        notes=payload.notes,
        source=payload.source,
    )
    db.add(AuditLog(
        user_id=token.sub,
        action=AuditAction.QUOTE_SUBMITTED,
        resource="supplier_quotes",
        resource_id=str(quote.id),
        description=f"Quote {quote.reference} by {supplier.company_name}",
    ))
    await db.commit()
    return {
        "id": str(quote.id),
        "reference": quote.reference,
        "total": float(quote.total),
        "currency": quote.currency,
    }


@router.post("/{rfq_id}/compare")
async def compare_rfq(
    rfq_id: str,
    payload: CompareIn,
    db: DBSession,
    token: CurrentToken,
):
    rfq = (await db.execute(select(RFQ).where(RFQ.id == rfq_id))).scalar_one_or_none()
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found")
    result = await compare_quotes(db, rfq, weights=payload.weights, save=payload.save)
    await db.commit()
    return result


# --- Marketplace simulator ---------------------------------------------


class SimulateIn(BaseModel):
    """Request body for ``POST /rfq/{rfq_id}/simulate``.

    The seed controls bid-war replay (same seed + same RFQ = same bids).
    The weights override the comparison scoring. The
    counter_offer_terms nudge round-2 bids downward.
    """

    seed: int = Field(default=42, ge=0, le=2**31 - 1)
    weights: dict[str, float] | None = None
    counter_offer_terms: dict[str, Any] | None = None


@router.post("/{rfq_id}/simulate")
async def simulate_bidding(
    rfq_id: str,
    payload: SimulateIn,
    db: DBSession,
    token: CurrentToken,
    dry_run: bool = Query(
        default=True,
        description=(
            "If true, bids are simulated and the comparison is run, but "
            "the RFQ is NOT transitioned to AWARDED and is_awarded is "
            "cleared. This lets the demo's what-if slider iterate "
            "without locking the RFQ. Set to false to commit the winner."
        ),
    ),
):
    """Run a marketplace simulator round for this RFQ.

    Round 1: every eligible supplier's agent bids.
    Round 2 (counter-offer): only the in-contention agents re-bid, with
    prices potentially squeezed by the counter-offer terms.

    Each call writes a batch of rows to ``market_sim_events`` so the
    frontend can render a timeline by polling the table.
    """
    if not token.has_permission("rfq:simulate:own"):
        raise HTTPException(
            status_code=403,
            detail="Missing permission: rfq:simulate:own",
        )

    from app.models.supplier import SupplierQuote

    rfq = (await db.execute(
        select(RFQ)
        .where(RFQ.id == rfq_id)
        .options(
            selectinload(RFQ.items),
            selectinload(RFQ.quotes).selectinload(SupplierQuote.supplier),
        )
    )).scalar_one_or_none()
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found")
    if rfq.status == RFQStatus.CANCELLED or rfq.status == RFQStatus.EXPIRED:
        raise HTTPException(
            status_code=400,
            detail=f"RFQ is {rfq.status.value}; cannot simulate bidding",
        )

    result = await run_market_sim(
        db,
        rfq,
        seed=payload.seed,
        weights=payload.weights,
        counter_offer_terms=payload.counter_offer_terms,
        dry_run=dry_run,
    )
    await db.commit()
    return result

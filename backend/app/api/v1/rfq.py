"""RFQ & Bidding routes — create RFQ, list quotes, compare, choose winner."""
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.deps.auth import (
    CurrentToken,
    DBSession,
    ReadDBSession,
    assert_vessel_access,
    require_permission,
)
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
from app.services.redaction import (
    hides_prices,
    seal_rfq_award_for_purchaser,
)
from app.services.marketplace import fan_out_rfq
from app.services.rfq import build_rfq_for_order, compare_quotes, submit_quote
from app.services.rfq_serializers import seal_comparison_response, seal_events

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
    token: Annotated[CurrentToken, Depends(require_permission("rfq", "read", "own"))],
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
    if not token.has_any_role(["super_admin", "fleet_admin"]):
        # Vessel-scoped list: only RFQs whose order.vessel_id matches
        # the caller's vessel_id. External users with no vessel get
        # an empty list (filtered out).
        stmt = stmt.join(Order, Order.id == RFQ.order_id)
        if token.vessel_id is not None:
            stmt = stmt.where(Order.vessel_id == token.vessel_id)
        else:
            stmt = stmt.where(False)  # external users see no RFQs
    stmt = stmt.limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()
    # The purchaser's view drops the awarded-quote id (it would tell
    # them which supplier won, which they're not allowed to know)
    # and the per-item target_unit_price (same rationale).
    purchaser_view = hides_prices(token.roles)
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
            "awarded_quote_id": (
                None if purchaser_view
                else (str(r.awarded_quote_id) if r.awarded_quote_id else None)
            ),
            "invited_count": r.invited_count,
            "responded_count": r.responded_count,
            "items": [
                {
                    "product_id": str(i.product_id),
                    "quantity": i.quantity,
                    "unit": i.unit,
                    "target_unit_price": (
                        None if purchaser_view
                        else (float(i.target_unit_price) if i.target_unit_price else None)
                    ),
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
    token: Annotated[CurrentToken, Depends(require_permission("rfq", "create", "own"))],
    response_deadline_hours: int | None = None,
):
    """Send the order to suppliers.

    IMPA-first redesign (migration 0007): this route uses the
    marketplace fan-out (``fan_out_rfq``) instead of the legacy
    sealed-bid builder (``build_rfq_for_order``). The marketplace
    flow invites every active supplier at the port — it doesn't
    filter on whether the supplier carries the specific products
    in the order, because the IMPA code is what the supplier is
    asked about. The legacy builder is kept on the
    ``build_rfq_for_order`` import for the 309 sealed-bid tests.

    Behavior:

      * Refuses to fire if the order is not in DRAFT (or
        AWAITING_CLARIFICATION? no — the admin must resolve the
        clarification thread first; the marketplace fan-out
        raises ValueError if there's an open question).
      * Snapshots the order's ETA + ETD from AIS.
      * Sets the order to QUOTING and the RFQ to SENT.
    """
    order = (await db.execute(select(Order).where(Order.id == order_id))).scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    # Vessel scope: the order's vessel must be in the caller's scope
    await assert_vessel_access(token, order.vessel_id)
    try:
        rfq = await fan_out_rfq(
            db, order, response_deadline_hours=response_deadline_hours
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
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
        "responded_count": rfq.responded_count,
        "response_deadline": rfq.response_deadline.isoformat(),
        "eta_at_port": getattr(order, "eta_at_port", None).isoformat() if getattr(order, "eta_at_port", None) else None,
        "etd_at_port": getattr(order, "etd_at_port", None).isoformat() if getattr(order, "etd_at_port", None) else None,
    }


@router.get("/{rfq_id}")
async def get_rfq(
    rfq_id: str,
    db: ReadDBSession,
    token: Annotated[CurrentToken, Depends(require_permission("rfq", "read", "own"))],
):
    rfq = (
        await db.execute(
            select(RFQ)
            .options(
                selectinload(RFQ.items),
                selectinload(RFQ.order),
                selectinload(RFQ.quotes).selectinload(SupplierQuote.supplier),
            )
            .where(RFQ.id == rfq_id)
        )
    ).scalar_one_or_none()
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found")
    # Vessel scope check via the order's vessel
    await assert_vessel_access(token, rfq.order.vessel_id if rfq.order else None)
    # Purchaser view: drop target_unit_price on each item; awarded
    # view drops supplier_name on quotes. Non-awarded RFQs return
    # the same shape the unsealed callers get, but with
    # target_unit_price = null.
    purchaser_view = hides_prices(token.roles)
    if purchaser_view:
        # On an awarded RFQ, the purchaser's view collapses to the
        # winner's total + lead time + payment terms. The other
        # bidders' identities stay sealed (they're not present in
        # the response at all).
        if rfq.status == RFQStatus.AWARDED and rfq.awarded_quote_id is not None:
            winner_quote = next(
                (q for q in rfq.quotes if str(q.id) == str(rfq.awarded_quote_id)),
                None,
            )
            if winner_quote is not None:
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
                            "target_unit_price": None,
                        }
                        for i in rfq.items
                    ],
                    "award": {
                        "total": float(winner_quote.total),
                        "currency": winner_quote.currency,
                        "lead_time_days": winner_quote.lead_time_days,
                        "payment_terms": winner_quote.payment_terms,
                        "score": winner_quote.score,
                    },
                }
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
                "target_unit_price": (
                    None if purchaser_view
                    else (float(i.target_unit_price) if i.target_unit_price else None)
                ),
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


@router.get("/{rfq_id}/lattice")
async def get_rfq_lattice(
    rfq_id: str,
    db: ReadDBSession,
    token: Annotated[CurrentToken, Depends(require_permission("marketplace", "compose", "global"))],
):
    """Admin view: the lattice the marketplace page renders.

    Rows = RFQ items, columns = suppliers who submitted a quote.
    Each cell carries the supplier's per-line decision (full / partial
    / none), the unit price they offered, and the lead time. This
    is the input the admin uses to make the per-line decision step
    (``POST /rfq/{rfq_id}/compose``).

    Suppliers who did not submit a quote are *not* included in the
    columns — the fan-out is "all active at the port", and the
    response-count field on the RFQ row tells the admin how many
    are missing.
    """
    rfq = (
        await db.execute(
            select(RFQ)
            .options(
                selectinload(RFQ.items),
                selectinload(RFQ.order),
                selectinload(RFQ.quotes)
                    .selectinload(SupplierQuote.supplier),
                selectinload(RFQ.quotes)
                    .selectinload(SupplierQuote.items),
            )
            .where(RFQ.id == rfq_id)
        )
    ).scalar_one_or_none()
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found")
    if rfq.order is not None:
        await assert_vessel_access(token, rfq.order.vessel_id)
    # The lattice is rows = rfq.items, columns = suppliers who
    # submitted a quote. Each cell is the supplier's per-line answer
    # for that product. The join between RFQItem and QuoteItem is
    # product_id (the marketplace redesign is one product per RFQ
    # item — see build_rfq_for_order).
    cells: list[dict[str, Any]] = []
    for item in rfq.items:
        row = {
            "rfq_item_id": str(item.id),
            "product_id": str(item.product_id),
            "quantity": item.quantity,
            "unit": item.unit,
            "description": item.description,
            "impa_code": item.impa_code,
            "cells": {},
        }
        for q in rfq.quotes:
            qi = next(
                (it for it in q.items if str(it.product_id) == str(item.product_id)),
                None,
            )
            if qi is None:
                row["cells"][str(q.supplier_id)] = None  # no bid on this line
            else:
                row["cells"][str(q.supplier_id)] = {
                    "line_status": qi.line_status,
                    "unit_price": float(qi.unit_price),
                    "quoted_quantity": qi.quoted_quantity,
                    "line_total": float(qi.line_total),
                }
        cells.append(row)
    return {
        "rfq_id": str(rfq.id),
        "reference": rfq.reference,
        "order_id": str(rfq.order_id),
        "order_reference": rfq.order.reference if rfq.order else None,
        "status": rfq.status.value,
        "eta_at_port": rfq.order.eta_at_port.isoformat() if rfq.order and rfq.order.eta_at_port else None,
        "responded_count": rfq.responded_count,
        "invited_count": rfq.invited_count,
        "suppliers": [
            {
                "supplier_id": str(q.supplier_id),
                "supplier_name": q.supplier.company_name,
                "quote_id": str(q.id),
                "quote_reference": q.reference,
                "lead_time_days": q.lead_time_days,
                "payment_terms": q.payment_terms,
                "currency": q.currency,
                "total": float(q.total),
            }
            for q in rfq.quotes
        ],
        "items": cells,
    }


@router.post("/quotes")
async def submit_quote_route(
    payload: QuoteIn,
    db: DBSession,
    token: Annotated[CurrentToken, Depends(require_permission("quotes", "submit", "own"))],
):
    rfq = (
        await db.execute(
            select(RFQ)
            .options(selectinload(RFQ.order))
            .where(RFQ.id == payload.rfq_id)
        )
    ).scalar_one_or_none()
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found")
    # Suppliers don't have a vessel; they just need to belong to the
    # destination port of the RFQ (already enforced by the SupplierPort
    # join in submit_quote). No vessel-scope check needed here.
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
    token: Annotated[CurrentToken, Depends(require_permission("quotes", "compare", "own"))],
):
    rfq = (
        await db.execute(
            select(RFQ)
            .options(
                selectinload(RFQ.order),
                # compare_quotes reads rfq.quotes (and walks each
                # quote.supplier), so eager-load both to avoid a
                # MissingGreenlet on the lazy reload.
                selectinload(RFQ.quotes).selectinload(SupplierQuote.supplier),
            )
            .where(RFQ.id == rfq_id)
        )
    ).scalar_one_or_none()
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found")
    await assert_vessel_access(token, rfq.order.vessel_id if rfq.order else None)
    result = await compare_quotes(db, rfq, weights=payload.weights, save=payload.save)
    await db.commit()
    # Sealed-bid redaction: non-admin callers (purchasing_officer,
    # chief_steward, etc.) see Bidder N labels + winner's total/lead
    # time + score ranking only. Admins see the full results.
    sealed = seal_comparison_response(result, token.roles)
    # The purchaser's view drops the bidder table entirely — they
    # see only the winning bid's total + lead time. (Other sealed
    # callers — chief_steward, vessel_captain — still get the bidder
    # table; the price-hiding rule is unique to the purchaser.)
    if hides_prices(token.roles):
        return seal_rfq_award_for_purchaser({}, sealed)
    return sealed


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
    token: Annotated[CurrentToken, Depends(require_permission("rfq", "simulate", "own"))],
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
    from sqlalchemy.orm import selectinload

    from app.models.supplier import SupplierQuote

    rfq = (await db.execute(
        select(RFQ)
        .where(RFQ.id == rfq_id)
        .options(
            selectinload(RFQ.items),
            selectinload(RFQ.order),
            selectinload(RFQ.quotes).selectinload(SupplierQuote.supplier),
        )
    )).scalar_one_or_none()
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found")
    # Vessel scope check via the order
    await assert_vessel_access(token, rfq.order.vessel_id if rfq.order else None)
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
    # Sealed-bid redaction: non-admin callers see the bid war as
    # Bidder 1, Bidder 2, ... with the winner's total/lead time.
    # The events list also gets supplier_id stripped, and any
    # counter_offer event with visibility=winner_only is reduced to
    # a redacted stub.
    sealed = seal_comparison_response(result, token.roles)
    if "events" in sealed:
        sealed["events"] = seal_events(sealed["events"], token.roles)
    return sealed

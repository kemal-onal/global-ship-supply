"""RFQ & Bidding routes — create RFQ, list quotes, compare, choose winner."""
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

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
    stmt = select(RFQ).order_by(RFQ.created_at.desc())
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
    rfq = (await db.execute(select(RFQ).where(RFQ.id == rfq_id))).scalar_one_or_none()
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

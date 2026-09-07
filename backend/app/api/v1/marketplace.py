"""Marketplace routes — admin composes the proposal, drops slow suppliers,
snapshots the ETA.

Routes:
  POST  /api/v1/rfq/{rfq_id}/compose            [admin]
  POST  /api/v1/orders/{order_id}/approve-proposal   [purchaser]
  POST  /api/v1/orders/{order_id}/drop-supplier      [admin]
  GET   /api/v1/orders/{order_id}/proposal           [purchaser or admin]
  POST  /api/v1/orders/{order_id}/snapshot-eta       [admin]

The "compose" route is mounted under /rfq/ because the input
unit is an RFQ, not an order. The "approve" and "drop" routes
are mounted under /orders/ because their effects are on the
order (status transition + assignment state).
"""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
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
from app.models.order import Order, OrderStatus
from app.models.supplier import (
    OrderDecision,
    RFQ,
    RFQStatus,
    Supplier,
    SupplierLineAssignment,
)
from app.services import marketplace as marketplace_svc

router = APIRouter()


# ── Schemas ────────────────────────────────────────────────────────


class DecisionIn(BaseModel):
    rfq_item_id: str
    supplier_id: str
    quote_id: str
    decision: str = Field(pattern="^(use_full|use_half|drop)$")


class ComposeIn(BaseModel):
    decisions: list[DecisionIn] = Field(min_length=1)
    margin_pct: float = Field(ge=0, le=100, default=8.0)


class ApproveIn(BaseModel):
    approve: bool
    reason: str | None = None


class DropIn(BaseModel):
    supplier_id: str
    reason: str = "manual_drop"


# ── Helpers ────────────────────────────────────────────────────────


async def _load_rfq_or_404(db, rfq_id: UUID, token) -> RFQ:
    rfq = (await db.execute(
        select(RFQ)
        .options(selectinload(RFQ.items), selectinload(RFQ.order))
        .where(RFQ.id == rfq_id)
    )).scalar_one_or_none()
    if rfq is None:
        raise HTTPException(status_code=404, detail="RFQ not found")
    if rfq.order is not None:
        await assert_vessel_access(token, rfq.order.vessel_id)
    return rfq


async def _load_order_or_404(db, order_id: UUID, token) -> Order:
    o = (await db.execute(select(Order).where(Order.id == order_id))).scalar_one_or_none()
    if not o:
        raise HTTPException(status_code=404, detail="Order not found")
    await assert_vessel_access(token, o.vessel_id)
    return o


# ── Routes ─────────────────────────────────────────────────────────


@router.post("/rfq/{rfq_id}/compose")
async def compose(
    rfq_id: UUID,
    payload: ComposeIn,
    db: DBSession,
    token: Annotated[CurrentToken, Depends(require_permission("marketplace", "compose", "global"))],
):
    rfq = await _load_rfq_or_404(db, rfq_id, token)
    if rfq.status == RFQStatus.CANCELLED or rfq.status == RFQStatus.EXPIRED:
        raise HTTPException(
            status_code=400,
            detail=f"RFQ is {rfq.status.value}; cannot compose proposal",
        )
    try:
        rows = await marketplace_svc.compose_proposal(
            db,
            rfq,
            decisions=[d.model_dump() for d in payload.decisions],
            margin_pct=payload.margin_pct,
            composed_by=token.sub,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # Refresh the order to read the new status after the service moved it.
    await db.flush()
    order = (await db.execute(select(Order).where(Order.id == rfq.order_id))).scalar_one()
    db.add(AuditLog(
        user_id=token.sub,
        action=AuditAction.PROPOSAL_COMPOSED,
        resource="orders",
        resource_id=str(order.id),
        description=f"Composed proposal with {len(rows)} decisions, margin={payload.margin_pct}%",
        extra={"rfq_id": str(rfq.id), "margin_pct": payload.margin_pct, "decision_count": len(rows)},
    ))
    await db.commit()
    return {
        "order_id": str(order.id),
        "rfq_id": str(rfq.id),
        "status": order.status.value,
        "margin_pct": payload.margin_pct,
        "decisions": [
            {
                "rfq_item_id": str(d.rfq_item_id),
                "supplier_id": str(d.supplier_id),
                "decision": d.decision,
                "used_quantity": d.used_quantity,
                "line_total": float(d.line_total),
                "customer_facing_total": float(d.customer_facing_total),
            }
            for d in rows
        ],
    }


@router.post("/orders/{order_id}/approve-proposal")
async def approve(
    order_id: UUID,
    payload: ApproveIn,
    db: DBSession,
    token: Annotated[CurrentToken, Depends(require_permission("marketplace", "approve", "own"))],
):
    order = await _load_order_or_404(db, order_id, token)
    try:
        result = await marketplace_svc.purchaser_approve_proposal(
            db, order, approve=payload.approve, reason=payload.reason, actor_id=token.sub
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    audit_action = AuditAction.PROPOSAL_APPROVED if payload.approve else AuditAction.PROPOSAL_REJECTED
    db.add(AuditLog(
        user_id=token.sub,
        action=audit_action,
        resource="orders",
        resource_id=str(order.id),
        description=(
            f"Proposal {'approved' if payload.approve else 'rejected'} on {order.reference}"
            + (f": {payload.reason}" if payload.reason and not payload.approve else "")
        ),
        after={"status": order.status.value, "reason": payload.reason},
    ))
    await db.commit()
    return result


@router.post("/orders/{order_id}/drop-supplier")
async def drop_supplier(
    order_id: UUID,
    payload: DropIn,
    db: DBSession,
    token: Annotated[CurrentToken, Depends(require_permission("marketplace", "drop", "global"))],
):
    """Admin manually drops a supplier's pending assignment.

    Finds every pending assignment for the given supplier on the
    given order and drops them. Used for the rare case where a
    supplier confirms by phone that they can't fulfil; the
    24h auto-drop is the more common path.
    """
    order = await _load_order_or_404(db, order_id, token)
    pending = (await db.execute(
        select(SupplierLineAssignment).where(
            SupplierLineAssignment.order_id == order.id,
            SupplierLineAssignment.supplier_id == payload.supplier_id,
            SupplierLineAssignment.line_status == "pending",
        )
    )).scalars().all()
    if not pending:
        raise HTTPException(
            status_code=404,
            detail="No pending assignment for that supplier on this order",
        )
    dropped = 0
    for sla in pending:
        try:
            await marketplace_svc.drop_slow_supplier(db, sla, reason=payload.reason)
            dropped += 1
        except ValueError:
            continue
    db.add(AuditLog(
        user_id=token.sub,
        action=AuditAction.SLICE_DROPPED,
        resource="orders",
        resource_id=str(order.id),
        description=f"Manually dropped supplier {payload.supplier_id} on {order.reference}",
        extra={"supplier_id": payload.supplier_id, "reason": payload.reason, "count": dropped},
    ))
    await db.commit()
    return {"order_id": str(order.id), "supplier_id": payload.supplier_id, "dropped": dropped}


@router.get("/orders/{order_id}/proposal")
async def get_proposal(
    order_id: UUID,
    db: ReadDBSession,
    token: CurrentToken,
):
    """Read the composed proposal.

    For the purchaser: per-line totals with margin applied, lead
    time, payment terms. Supplier identities are sealed.
    For admins: full details including the supplier's unit_price
    and identity.
    """
    from app.services.redaction import hides_prices

    order = await _load_order_or_404(db, order_id, token)
    decisions = (await db.execute(
        select(OrderDecision)
        .options(
            selectinload(OrderDecision.rfq_item),
            selectinload(OrderDecision.supplier),
            selectinload(OrderDecision.quote),
        )
        .where(OrderDecision.order_id == order.id)
    )).scalars().all()
    if not decisions:
        return {
            "order_id": str(order.id),
            "status": order.status.value,
            "margin_pct": float(order.company_margin_pct) if order.company_margin_pct is not None else None,
            "eta_at_port": order.eta_at_port.isoformat() if order.eta_at_port else None,
            "lines": [],
            "subtotal": 0,
            "grand_total": 0,
        }
    purchaser_view = hides_prices(token.roles)
    lines = []
    customer_subtotal = 0.0
    for d in decisions:
        # Lead time comes from the quote. We walk via d.quote; the
        # service already loaded it.
        lead_days = d.quote.lead_time_days if d.quote else None
        customer_subtotal += float(d.customer_facing_total)
        if purchaser_view:
            lines.append({
                "rfq_item_id": str(d.rfq_item_id),
                "product_id": str(d.rfq_item.product_id) if d.rfq_item else None,
                "decision": d.decision,
                "used_quantity": d.used_quantity,
                "line_total": None,            # sealed
                "customer_facing_total": float(d.customer_facing_total),
                "lead_time_days": lead_days,
            })
        else:
            lines.append({
                "rfq_item_id": str(d.rfq_item_id),
                "product_id": str(d.rfq_item.product_id) if d.rfq_item else None,
                "supplier_id": str(d.supplier_id),
                "supplier_name": d.supplier.company_name if d.supplier else None,
                "decision": d.decision,
                "used_quantity": d.used_quantity,
                "unit_price": float(d.unit_price),
                "line_total": float(d.line_total),
                "customer_facing_total": float(d.customer_facing_total),
                "lead_time_days": lead_days,
            })
    return {
        "order_id": str(order.id),
        "status": order.status.value,
        "margin_pct": float(order.company_margin_pct) if order.company_margin_pct is not None else None,
        "eta_at_port": order.eta_at_port.isoformat() if order.eta_at_port else None,
        "lines": lines,
        "subtotal": None if purchaser_view else sum(float(d.line_total) for d in decisions),
        "customer_facing_subtotal": round(customer_subtotal, 4),
    }


@router.post("/orders/{order_id}/snapshot-eta")
async def snapshot_eta(
    order_id: UUID,
    db: DBSession,
    token: Annotated[CurrentToken, Depends(require_permission("marketplace", "compose", "global"))],
):
    """Take a fresh ETA snapshot and write it to the order.

    Usually called by ``fan_out_rfq`` automatically; this route
    is the manual refresh the admin can trigger if AIS data
    arrives late or the vessel changed destination.
    """
    from app.services.eta import write_eta_to_order
    order = await _load_order_or_404(db, order_id, token)
    snap = await write_eta_to_order(db, order)
    await db.commit()
    return {
        "order_id": str(order.id),
        "eta_at_port": order.eta_at_port.isoformat() if order.eta_at_port else None,
        "snapshot": {
            "eta": snap.eta.isoformat() if snap.eta else None,
            "last_report_ts": snap.last_report_ts.isoformat() if snap.last_report_ts else None,
            "source_report_id": snap.source_report_id,
            "is_stale": snap.is_stale,
        },
    }

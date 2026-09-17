"""Marketplace routes — admin composes the proposal, drops slow suppliers,
snapshots the ETA.

Routes:
  GET   /api/v1/rfqs-for-compose                    [admin]
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
    RFQ,
    RFQStatus,
    Supplier,
    SupplierQuote,
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
    # ``snapshot_eta_for_order`` reads ``order.port`` (the Port
    # relationship) — without the ``selectinload`` here that's a
    # lazy-load in async context, which triggers a
    # ``MissingGreenlet`` at runtime. The order is small, so the
    # eager load is cheap; the alternative is to thread the port
    # unlocode through every caller.
    o = (await db.execute(
        select(Order)
        .options(selectinload(Order.port), selectinload(Order.vessel))
        .where(Order.id == order_id)
    )).scalar_one_or_none()
    if not o:
        raise HTTPException(status_code=404, detail="Order not found")
    await assert_vessel_access(token, o.vessel_id)
    return o


# ── Routes ─────────────────────────────────────────────────────────


# Order statuses for which the admin can compose a proposal. This
# matches the self-heal allowlist in
# ``marketplace_svc.compose_proposal``: ready_for_compose is the
# marketplace redesign's normal path; the legacy sealed-bid
# predecessors (rfq_in_progress / bidding / awaiting_confirmation)
# are included because compose_proposal self-heals them to
# ready_for_compose before writing the new status. Exposing them
# here means the picker surfaces legacy orders that the admin can
# unblock by clicking compose.
_COMPOSE_ELIGIBLE_ORDER_STATUSES: tuple[OrderStatus, ...] = (
    # READY_FOR_COMPOSE removed (simplified flow)  # 
    OrderStatus.RFQ_SENT,
    # BIDDING removed  # 
    OrderStatus.AWAITING_CONFIRMATION,
)


@router.get("/rfqs-for-compose")
async def list_rfqs_for_compose(
    db: ReadDBSession,
    token: Annotated[CurrentToken, Depends(require_permission("marketplace", "compose", "global"))],
    limit: int = 50,
    offset: int = 0,
):
    """List the RFQs whose orders are eligible for proposal composition.

    The marketplace admin's left-rail picker calls this. We filter
    by **order status**, not RFQ status — the picker wants RFQs
    whose order is ready for the per-line decision step, which
    corresponds to the order states ``ready_for_compose`` plus the
    legacy sealed-bid predecessors (which the compose service
    self-heals).

    Why not filter by ``RFQ.status == OPEN``? Because once every
    invited supplier has responded, ``supplier_submit_quote`` flips
    the RFQ to ``closed`` and the order to ``ready_for_compose`` —
    the two are the same fact seen from different sides. Querying
    by order status is the stable, semantically correct view, and
    it gracefully includes the legacy sealed-bid RFQs whose
    status stayed ``open`` because their quotes were injected by
    the simulator rather than going through the submit service.

    The response shape matches what the picker renders: id,
    reference, order_id, order_reference, port_id, status, the
    response counters, and the line items.
    """
    stmt = (
        select(RFQ)
        .join(Order, Order.id == RFQ.order_id)
        .options(selectinload(RFQ.order), selectinload(RFQ.items))
        .where(Order.status.in_(_COMPOSE_ELIGIBLE_ORDER_STATUSES))
        .order_by(RFQ.created_at.desc())
    )
    if not token.has_any_role(["super_admin", "fleet_admin"]):
        # Vessel-scoped view: only RFQs whose order.vessel_id
        # matches the caller's vessel_id. External users with no
        # vessel get an empty list.
        if token.vessel_id is not None:
            stmt = stmt.where(Order.vessel_id == token.vessel_id)
        else:
            stmt = stmt.where(False)
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
            "invited_count": r.invited_count,
            "responded_count": r.responded_count,
            "items": [
                {
                    "product_id": str(i.product_id),
                    "quantity": i.quantity,
                    "unit": i.unit,
                }
                for i in r.items
            ],
        }
        for r in rows
    ]


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
    """Admin drops a supplier from the order.

    In the simplified marketplace, suppliers submit single-form quotes
    and there are no 24h slice assignments to drop. This route is
    kept for backward compatibility but always returns 404 since
    SupplierLineAssignment is no longer tracked.
    """
    order = await _load_order_or_404(db, order_id, token)
    raise HTTPException(
        status_code=404,
        detail="No pending assignment for that supplier on this order — simplified flow has no slice assignments",
    )


@router.get("/orders/{order_id}/proposal")
async def get_proposal(
    order_id: UUID,
    db: ReadDBSession,
    token: CurrentToken,
):
    """Read the order proposal in the simplified marketplace.

    In the simplified flow, orders have a flat status and the
    purchaser approves/rejects the entire proposal. There are no
    per-line decisions (OrderDecision) — the admin applies a uniform
    markup % to all supplier quotes, then the purchaser decides.

    Returns the order status and margin info for the purchaser view.
    """
    from app.services.redaction import hides_prices

    # Demo: purchaser = general (all vessels) — skip vessel scope
    o = (await db.execute(
        select(Order)
        .options(selectinload(Order.port), selectinload(Order.vessel))
        .where(Order.id == order_id)
    )).scalar_one_or_none()
    if not o:
        raise HTTPException(status_code=404, detail="Order not found")
    order = o

    # Build payload base — company_margin_pct removed by migration 0009; derive from data
    payload = {
        "order_id": str(order.id),
        "status": order.status.value,
        "margin_pct": 0.0,
        "eta_at_port": None,
        "lines": [],
        "subtotal": 0,
        "customer_facing_subtotal": 0,
        "note": "",
    }

    # Simplified flow: proposal built from RFQ data (redesigned OrderDecision
    # model is not loaded in this simplified deployment; use RFQ + quotes)
    rfq_rows = (await db.execute(
        select(RFQ)
        .options(selectinload(RFQ.items), selectinload(RFQ.quotes).selectinload(SupplierQuote.items))
        .where(RFQ.order_id == order_id)
    )).scalars().all()
    rfq = rfq_rows[0] if rfq_rows else None
    if rfq:
        payload["margin_pct"] = float(rfq.markup_pct or 0)
        payload["lines"] = [
            {
                "rfq_item_id": str(item.id),
                "quantity": item.quantity,
                "used_quantity": item.quantity,
                "line_total": float(item.quantity * (float(rfq.markup_pct or 0) / 100 + 1) if item.quantity else 0),
                "customer_facing_total": float(item.quantity * (float(rfq.markup_pct or 0) / 100 + 1) if item.quantity else 0),
                "decision": "use_full",  # simplified flow: full proposal
                "lead_time_days": None,
            }
            for item in rfq.items
        ]
        subtotal = sum((q.subtotal or 0) for q in rfq.quotes)
        customer_facing_subtotal = sum((q.customer_facing_total or q.marked_up_total or q.total or 0) for q in rfq.quotes)
        payload["subtotal"] = float(subtotal)
        payload["customer_facing_subtotal"] = float(customer_facing_subtotal)
        payload["note"] = "Simplified flow: admin applies uniform markup; purchaser approves/rejects entire proposal"
    else:
        payload["note"] = "No composed proposal or RFQ found for this order."

    # Filter at last — but purchaser MUST see price + qty at proposal review stage.
    # Only strip if this were a sealed-bid catalog view (not proposal approval).
    return payload


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

"""Order routes — list, get, create with customs preflight, update status."""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from app.deps.auth import CurrentToken, DBSession, ReadDBSession
from app.models.audit import AuditAction, AuditLog
from app.models.order import Order, OrderItem, OrderPriority, OrderStatus
from app.models.product import Product
from app.services.customs import evaluate_order, has_blocking_issue, summarize
from app.services.notifications import notify_order_transition
from app.services.redaction import (
    hides_prices,
    is_supplier,
    seal_order_for_purchaser,
    seal_order_for_supplier,
)

router = APIRouter()


class OrderItemIn(BaseModel):
    # IMPA-first redesign (migration 0007): the catalog
    # cross-reference is gone. ``product_id`` is now optional
    # (kept for back-compat with the old picker; new code
    # should send ``impa_code`` instead). The supplier is the
    # source of truth for whether the IMPA maps to a real
    # product.
    product_id: Optional[str] = None
    # The IMPA code the purchaser typed or picked from the
    # typeahead. Free-text (NOT a FK) — the typeahead is just
    # a convenience against the ImpaCode table. Indexed in
    # the DB for the supplier portal / lattice lookups.
    impa_code: Optional[str] = None
    quantity: int = Field(gt=0)
    unit: str = "pcs"
    # IMPA-first: the order line carries no price. The server
    # always writes 0 regardless of what the client sends.
    # The column is kept on OrderItem to preserve the existing
    # subtotal / grand_total machinery (always 0) and the 309
    # sealed-bid test fixtures.
    unit_price: float = Field(default=0, ge=0)
    notes: Optional[str] = None
    # Marketplace redesign: the purchaser's "intended use" text is
    # forwarded to suppliers so they can price a line against what
    # it's actually for (footwear vs. protective footwear). Stored
    # on OrderItem.notes for backwards compatibility; the marketplace
    # flow copies it to RFQItem.description when the RFQ is built.
    description: Optional[str] = None


class OrderIn(BaseModel):
    vessel_id: str
    port_id: str
    priority: OrderPriority = OrderPriority.NORMAL
    required_by: Optional[datetime] = None
    customer_notes: Optional[str] = None
    internal_notes: Optional[str] = None
    items: list[OrderItemIn] = Field(min_length=1)
    # Used by offline clients
    client_id: Optional[str] = None
    client_created_at: Optional[datetime] = None
    source: str = "web"
    # Marketplace redesign: signal to the product picker that the
    # frontend is doing an IMPA substring search. Informational
    # only — the picker already supports `?q=`. Kept on the order
    # for audit / analytics so we can later see "X% of orders used
    # IMPA search" without a separate analytics pipeline.
    search_by_impa: bool = False


def _serialize(o: Order, *, caller_roles: list[str]) -> dict:
    """Build the wire payload for an order, then apply the caller's
    view filter (purchaser / supplier / company). The DB always holds
    the truth; the filter is the only thing the caller sees.

    IMPA-first redesign (migration 0007): the order line carries
    no price. ``unit_price`` and ``line_total`` are still in the
    DB (always 0) for legacy machinery, but they are NOT surfaced
    to any role on this endpoint. The supplier's quote is the
    only place a price appears in the marketplace flow.
    """
    payload = {
        "id": str(o.id),
        "reference": o.reference,
        "vessel_id": str(o.vessel_id),
        "vessel_name": o.vessel.name if o.vessel else None,
        "port_id": str(o.port_id),
        "port_name": o.port.name if o.port else None,
        "status": o.status.value,
        "priority": o.priority.value,
        "order_date": o.order_date.isoformat(),
        "required_by": o.required_by.isoformat() if o.required_by else None,
        "estimated_delivery": o.estimated_delivery.isoformat() if o.estimated_delivery else None,
        "currency": o.currency,
        # IMPA-first: grand_total is always 0 (no prices on the
        # order). Kept on the wire for back-compat with any client
        # still rendering it; the value is always 0 now.
        "subtotal": float(o.subtotal),
        "tax_total": float(o.tax_total),
        "shipping_total": float(o.shipping_total),
        "grand_total": float(o.grand_total),
        # IMPA-first: ETA/ETD snapshot from the fan-out step. Null
        # for orders that haven't been sent to suppliers yet (no
        # AIS available, or the fan-out hasn't run).
        "eta_at_port": o.eta_at_port.isoformat() if o.eta_at_port else None,
        "etd_at_port": o.etd_at_port.isoformat() if o.etd_at_port else None,
        "customer_notes": o.customer_notes,
        "internal_notes": o.internal_notes,
        "source": o.source,
        "client_id": o.client_id,
        "created_by": str(o.created_by),
        "items": [
            {
                "id": str(it.id),
                "product_id": str(it.product_id) if it.product_id else None,
                "product_name": it.product.name if it.product else None,
                "product_sku": it.product.sku if it.product else None,
                "impa_code": it.impa_code,
                "quantity": it.quantity,
                "unit": it.unit,
                "notes": it.notes,
            }
            for it in o.items
        ],
        "regulation_warnings": o.regulation_warnings or [],
    }
    if is_supplier(caller_roles):
        return seal_order_for_supplier(payload)
    if hides_prices(caller_roles):
        return seal_order_for_purchaser(payload)
    return payload


@router.get("")
async def list_orders(
    db: ReadDBSession,
    token: CurrentToken,
    vessel_id: str | None = Query(None),
    port_id: str | None = Query(None),
    status: OrderStatus | None = Query(None),
    q: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    stmt = (
        select(Order)
        .order_by(Order.order_date.desc())
        # Eager-load the relationships _serialize() touches so the
        # async session doesn't try to lazy-load after the route
        # returns (MissingGreenlet).
        .options(
            selectinload(Order.vessel),
            selectinload(Order.port),
            selectinload(Order.items).selectinload(OrderItem.product),
        )
    )
    if vessel_id:
        stmt = stmt.where(Order.vessel_id == vessel_id)
    if port_id:
        stmt = stmt.where(Order.port_id == port_id)
    if status:
        stmt = stmt.where(Order.status == status)
    if q:
        stmt = stmt.where(or_(Order.reference.ilike(f"%{q}%"), Order.customer_notes.ilike(f"%{q}%")))
    stmt = stmt.limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().unique().all()
    return [_serialize(o, caller_roles=token.roles) for o in rows]


@router.get("/{order_id}")
async def get_order(
    order_id: str,
    db: ReadDBSession,
    token: CurrentToken,
):
    stmt = (
        select(Order)
        .where(Order.id == order_id)
        .options(
            selectinload(Order.vessel),
            selectinload(Order.port),
            selectinload(Order.items).selectinload(OrderItem.product),
        )
    )
    o = (await db.execute(stmt)).scalar_one_or_none()
    if not o:
        raise HTTPException(status_code=404, detail="Order not found")
    return _serialize(o, caller_roles=token.roles)


@router.post("")
async def create_order(
    payload: OrderIn,
    db: DBSession,
    token: CurrentToken,
):
    """Create an order. Runs the customs filter and includes the result
    in `regulation_warnings` (advisory, does not block creation).

    IMPA-first redesign (migration 0007): the order line has no
    price. ``product_id`` is optional and only kept on rows that
    have it (legacy / sealed-bid tests). The purchaser's typed
    ``impa_code`` is the primary cross-reference; the supplier is
    the source of truth for whether the IMPA maps to a real
    product. ``unit_price`` and ``line_total`` are always 0 on
    new rows; the order's subtotal/grand_total stays 0.
    """
    # Validate products (only if any lines still carry one). The
    # IMPA-first flow doesn't require a product FK, but legacy
    # callers / sealed-bid tests may still send it. We accept the
    # line as long as the product exists; otherwise we 400.
    product_ids = {item.product_id for item in payload.items if item.product_id}
    product_map: dict[str, Product] = {}
    if product_ids:
        products = (await db.execute(
            select(Product).where(Product.id.in_(product_ids))
        )).scalars().all()
        product_map = {str(p.id): p for p in products}
        for item in payload.items:
            if item.product_id and item.product_id not in product_map:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unknown product: {item.product_id}",
                )

    # IMPA-first: at least one of (product_id, impa_code) must be
    # present on every line. The IMPA typeahead makes this easy for
    # the purchaser; a stray product_id without an IMPA is fine
    # (back-compat); a stray IMPA without a product_id is also fine
    # (the new flow). The "no identifier at all" case is a 400.
    for item in payload.items:
        if not item.product_id and not (item.impa_code and item.impa_code.strip()):
            raise HTTPException(
                status_code=400,
                detail="Each line needs at least an impa_code or product_id",
            )

    reference = f"AVS-{datetime.now(timezone.utc).strftime('%Y')}-{int(datetime.now(timezone.utc).timestamp()) % 1000000:06d}"

    order = Order(
        reference=reference,
        vessel_id=payload.vessel_id,
        port_id=payload.port_id,
        status=OrderStatus.DRAFT,
        priority=payload.priority,
        required_by=payload.required_by,
        customer_notes=payload.customer_notes,
        internal_notes=payload.internal_notes,
        source=payload.source,
        client_id=payload.client_id,
        client_created_at=payload.client_created_at,
        created_by=token.sub,
    )
    for item in payload.items:
        # IMPA-first: the line carries no price. unit_price and
        # line_total are always 0 (the column stays in the DB for
        # the legacy subtotal/grand_total machinery and the
        # sealed-bid test fixtures).
        unit_price = 0.0
        line_total = 0.0
        # The marketplace redesign uses OrderItem.notes as the
        # "intended use" channel: the RFQ builder copies notes
        # into RFQItem.description when fanning out. If the
        # caller sent `description` but no `notes`, prefer the
        # description so the supplier sees it. If both are set,
        # they get appended (description first; the legacy
        # notes value is the free-form purchaser comment).
        merged_notes = None
        if item.description and item.notes:
            merged_notes = f"{item.description}\n---\n{item.notes}"
        elif item.description:
            merged_notes = item.description
        else:
            merged_notes = item.notes
        order.items.append(OrderItem(
            product_id=item.product_id,  # may be None
            impa_code=item.impa_code,
            quantity=item.quantity,
            unit=item.unit,
            unit_price=unit_price,
            line_total=line_total,
            notes=merged_notes,
        ))
    # IMPA-first: subtotal/grand_total stay 0 (no prices on the
    # order). Kept on the parent so the column contract is
    # preserved for the rest of the schema / tests.
    order.subtotal = 0
    order.tax_total = 0
    order.shipping_total = 0
    order.grand_total = 0
    db.add(order)
    await db.flush()
    await db.refresh(order, attribute_names=["vessel", "port", "items"])

    # Customs preflight (unchanged). The regulation engine still
    # reads product_id for product-based rules; lines without a
    # product_id (IMPA-only) are skipped.
    try:
        issues = await evaluate_order(db, order)
        order.regulation_warnings = [
            {
                "severity": i.severity,
                "title": i.title,
                "description": i.description,
                "source": i.source,
                "can_override": i.can_override,
                "requires_permit": i.requires_permit,
                "matched_product_ids": i.matched_product_ids or [],
                "rule_id": i.rule_id,
            }
            for i in issues
        ]
        order.customs_clearance_required = has_blocking_issue(issues) or bool(issues)
    except Exception:
        # Don't fail the create on customs engine errors; surface them in the response
        order.regulation_warnings = [{"error": "Regulation engine unavailable"}]

    # Audit
    db.add(AuditLog(
        user_id=token.sub,
        action=AuditAction.ORDER_PLACED,
        resource="orders",
        resource_id=str(order.id),
        description=f"Order {order.reference} created with {len(order.items)} items",
        extra={
            "grand_total": float(order.grand_total),
            "source": payload.source,
            "search_by_impa": payload.search_by_impa,
        },
    ))

    await db.commit()
    # Eager-load relationships needed for _serialize — async sessions
    # can't lazy-load, so we re-query with selectinload.
    stmt = (
        select(Order)
        .options(
            selectinload(Order.vessel),
            selectinload(Order.port),
            selectinload(Order.items).selectinload(OrderItem.product),
        )
        .where(Order.id == order.id)
    )
    order = (await db.execute(stmt)).scalar_one()
    return _serialize(order, caller_roles=token.roles)


@router.post("/{order_id}/transition")
async def transition_order(
    order_id: str,
    new_status: OrderStatus,
    db: DBSession,
    token: CurrentToken,
    reason: str | None = None,
):
    o = (await db.execute(select(Order).where(Order.id == order_id))).scalar_one_or_none()
    if not o:
        raise HTTPException(status_code=404, detail="Order not found")
    old = o.status
    o.status = new_status
    if new_status in (OrderStatus.CANCELLED, OrderStatus.REJECTED) and reason:
        (o.cancellation_reason if new_status == OrderStatus.CANCELLED else o.rejection_reason)  # noqa: E501
        if new_status == OrderStatus.CANCELLED:
            o.cancellation_reason = reason
        else:
            o.rejection_reason = reason
    db.add(AuditLog(
        user_id=token.sub,
        action=AuditAction.UPDATE,
        resource="orders",
        resource_id=str(o.id),
        description=f"Status {old.value} -> {new_status.value}",
        before={"status": old.value},
        after={"status": new_status.value, "reason": reason},
    ))

    # Fire a notification to the order's owner (assigned_to or created_by).
    # The service no-ops if the actor is the recipient (self-spam guard).
    await notify_order_transition(db, o, old, actor_id=token.sub)

    await db.commit()
    return {"id": str(o.id), "old_status": old.value, "new_status": new_status.value}


@router.get("/{order_id}/assignments")
async def list_order_assignments(
    order_id: str,
    db: ReadDBSession,
    token: CurrentToken,
):
    """Admin view of the slices on a confirmed order.

    One row per OrderDecision that became a SupplierLineAssignment.
    Used by the OrderDetail preparation-status panel to show
    which suppliers have confirmed and which are still pending
    (and need dropping after the 24h window).
    """
    from app.deps.auth import assert_vessel_access
    from app.models.supplier import Supplier, SupplierLineAssignment

    o = (await db.execute(select(Order).where(Order.id == order_id))).scalar_one_or_none()
    if not o:
        raise HTTPException(status_code=404, detail="Order not found")
    await assert_vessel_access(token, o.vessel_id)
    rows = (await db.execute(
        select(SupplierLineAssignment)
        .options(
            selectinload(SupplierLineAssignment.supplier),
            selectinload(SupplierLineAssignment.rfq_item),
        )
        .where(SupplierLineAssignment.order_id == o.id)
        .order_by(SupplierLineAssignment.created_at.asc())
    )).scalars().all()
    return [
        {
            "id": str(sla.id),
            "rfq_item_id": str(sla.rfq_item_id),
            "supplier_id": str(sla.supplier_id),
            "supplier_name": sla.supplier.company_name if sla.supplier else None,
            "product_id": str(sla.rfq_item.product_id) if sla.rfq_item else None,
            "line_status": sla.line_status,
            "confirmed_at": sla.confirmed_at.isoformat() if sla.confirmed_at else None,
            "dropped_at": sla.dropped_at.isoformat() if sla.dropped_at else None,
            "drop_reason": sla.drop_reason,
            "preparation_deadline": sla.preparation_deadline.isoformat() if sla.preparation_deadline else None,
        }
        for sla in rows
    ]

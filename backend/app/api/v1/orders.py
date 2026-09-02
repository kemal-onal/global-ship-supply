"""Order routes — list, get, create with customs preflight, update status."""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from app.deps.auth import CurrentToken, DBSession, ReadDBSession
from app.models.audit import AuditAction, AuditLog
from app.models.order import Order, OrderItem, OrderPriority, OrderStatus
from app.models.product import Product
from app.services.customs import evaluate_order, has_blocking_issue, summarize
from app.services.notifications import notify_order_transition

router = APIRouter()


class OrderItemIn(BaseModel):
    product_id: str
    quantity: int = Field(gt=0)
    unit: str = "pcs"
    unit_price: float = Field(ge=0)
    notes: Optional[str] = None


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


def _serialize(o: Order) -> dict:
    return {
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
        "subtotal": float(o.subtotal),
        "tax_total": float(o.tax_total),
        "shipping_total": float(o.shipping_total),
        "grand_total": float(o.grand_total),
        "customer_notes": o.customer_notes,
        "internal_notes": o.internal_notes,
        "source": o.source,
        "client_id": o.client_id,
        "created_by": str(o.created_by),
        "items": [
            {
                "id": str(it.id),
                "product_id": str(it.product_id),
                "product_name": it.product.name if it.product else None,
                "product_sku": it.product.sku if it.product else None,
                "quantity": it.quantity,
                "unit": it.unit,
                "unit_price": float(it.unit_price),
                "line_total": float(it.line_total),
            }
            for it in o.items
        ],
        "regulation_warnings": o.regulation_warnings or [],
    }


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
    stmt = select(Order).order_by(Order.order_date.desc())
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
    return [_serialize(o) for o in rows]


@router.get("/{order_id}")
async def get_order(
    order_id: str,
    db: ReadDBSession,
    token: CurrentToken,
):
    o = (await db.execute(select(Order).where(Order.id == order_id))).scalar_one_or_none()
    if not o:
        raise HTTPException(status_code=404, detail="Order not found")
    return _serialize(o)


@router.post("")
async def create_order(
    payload: OrderIn,
    db: DBSession,
    token: CurrentToken,
):
    """Create an order. Runs the customs filter and includes the result
    in `regulation_warnings` (advisory, does not block creation)."""
    # Validate products
    product_ids = {item.product_id for item in payload.items}
    products = (await db.execute(select(Product).where(Product.id.in_(product_ids)))).scalars().all()
    product_map = {str(p.id): p for p in products}
    for item in payload.items:
        if item.product_id not in product_map:
            raise HTTPException(status_code=400, detail=f"Unknown product: {item.product_id}")

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
    subtotal = 0.0
    for item in payload.items:
        line_total = round(item.quantity * item.unit_price, 4)
        subtotal += line_total
        order.items.append(OrderItem(
            product_id=item.product_id,
            quantity=item.quantity,
            unit=item.unit,
            unit_price=item.unit_price,
            line_total=line_total,
            notes=item.notes,
        ))
    order.subtotal = round(subtotal, 4)
    order.grand_total = round(subtotal, 4)
    db.add(order)
    await db.flush()
    await db.refresh(order, attribute_names=["vessel", "port", "items"])

    # Customs preflight
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
        extra={"grand_total": float(order.grand_total), "source": payload.source},
    ))

    await db.commit()
    await db.refresh(order)
    return _serialize(order)


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

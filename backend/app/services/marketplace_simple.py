"""Simplified Marketplace Service.

The new simplified flow:
1. Order created by purchaser -> PENDING_APPROVAL
2. Admin sends RFQ to all active suppliers at port (fan-out)
3. Suppliers submit quotes — single form with all lines (full/partial/none
   + custom quantity + unit price) + lead_time_days + payment_terms
4. Admin applies uniform markup % to ALL quotes
5. Admin sends marked-up quotes to purchaser (RFQ -> CLOSED)
6. Purchaser approves/rejects entire proposal:
   - Approve: Order -> APPROVED, RFQ -> AWARDED
   - Reject: Order -> DRAFT, RFQ -> CANCELLED
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.order import Order, OrderStatus
from app.models.supplier import (
    QuoteItem,
    QuoteLineStatus,
    RFQ,
    RFQItem,
    RFQStatus,
    Supplier,
    SupplierPort,
    SupplierQuote,
    SupplierStatus,
)
from app.models.user import User


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_reference(prefix: str) -> str:
    return f"{prefix}-{_now().strftime('%Y%m%d-%H%M%S')}-{_uuid_short()}"


def _uuid_short() -> str:
    import uuid as _uuid
    return _uuid.uuid4().hex[:8]


async def fan_out_rfq(
    db: AsyncSession,
    order: Order,
    *,
    response_deadline_hours: int | None = None,
) -> RFQ:
    """Build the RFQ and invite every ACTIVE supplier at the port.

    The order moves to RFQ_SENT and the RFQ to SENT.
    """
    if order.status not in (OrderStatus.DRAFT, OrderStatus.PENDING_APPROVAL):
        raise ValueError(
            f"Cannot fan out from status {order.status.value}; expected DRAFT or PENDING_APPROVAL"
        )

    deadline_h = response_deadline_hours or settings.RFQ_RESPONSE_TIMEOUT_HOURS
    rfq = RFQ(
        reference=_new_reference("RFQ"),
        order_id=order.id,
        port_id=order.port_id,
        status=RFQStatus.SENT,
        sent_at=_now(),
        response_deadline=_now() + timedelta(hours=deadline_h),
        markup_pct=0,  # Admin will set this later
    )

    # Copy line items from order
    for oi in order.items:
        rfq.items.append(RFQItem(
            product_id=oi.product_id,
            quantity=oi.quantity,
            unit=oi.unit,
            target_unit_price=oi.unit_price,  # Usually 0 in IMPA-first flow
            description=oi.notes,
            impa_code=oi.impa_code,
        ))

    db.add(rfq)
    await db.flush()  # need rfq.id + rfq_item ids

    # Legacy backfill: for rfq_items where impa_code is still null
    needs_backfill = [ri for ri in rfq.items if not ri.impa_code and ri.product_id]
    if needs_backfill:
        from app.models.product import ImpaCode, Product
        product_ids = {ri.product_id for ri in needs_backfill}
        impa_rows = (await db.execute(
            select(Product.id, ImpaCode.code)
            .join(ImpaCode, ImpaCode.id == Product.impa_code_id)
            .where(Product.id.in_(product_ids))
        )).all()
        impa_map = {pid: code for pid, code in impa_rows}
        for ri in needs_backfill:
            ri.impa_code = impa_map.get(ri.product_id)

    # Find every active supplier at the port
    supplier_ids = (await db.execute(
        select(Supplier.id)
        .join(SupplierPort, SupplierPort.supplier_id == Supplier.id)
        .where(
            SupplierPort.port_id == order.port_id,
            Supplier.status == SupplierStatus.ACTIVE,
        )
    )).scalars().all()

    rfq.invited_count = len(supplier_ids)
    rfq.extra = {
        "invited_supplier_ids": [str(s) for s in supplier_ids],
    }
    order.status = OrderStatus.RFQ_SENT

    return rfq


async def supplier_submit_quote(
    db: AsyncSession,
    rfq: RFQ,
    supplier: Supplier,
    *,
    lines: list[dict[str, Any]],
    lead_time_days: int,
    payment_terms: str | None = None,
    notes: str | None = None,
    source: str = "portal",
) -> SupplierQuote:
    """Supplier submits a complete quote in a single form.

    ``lines`` shape:
      [
        {
          "rfq_item_id":    "<uuid>",
          "line_status":    "full" | "partial" | "none",
          "unit_price":     float (required for full/partial),
          "quoted_quantity": int  (required for partial, optional for full)
        },
        ...
      ]

    Re-submission overwrites the previous quote for the same (rfq, supplier).
    """
    if rfq.status not in (RFQStatus.SENT, RFQStatus.CLOSED):
        raise ValueError(f"RFQ is {rfq.status.value}; cannot accept quotes")
    if _now() > rfq.response_deadline:
        raise ValueError("RFQ response deadline passed")
    if supplier.status != SupplierStatus.ACTIVE:
        raise ValueError("Supplier not active")

    # Map rfq_item_ids to their target quantity/unit
    rfq_items = {str(ri.id): ri for ri in rfq.items}

    # Drop the existing quote if any (re-submission)
    existing = (await db.execute(
        select(SupplierQuote).where(
            SupplierQuote.rfq_id == rfq.id,
            SupplierQuote.supplier_id == supplier.id,
        )
    )).scalar_one_or_none()
    if existing is not None:
        await db.delete(existing)
        await db.flush()
        # Decrement responded_count since we're replacing
        rfq.responded_count = max(0, rfq.responded_count - 1)

    # Resolve product_id for IMPA-first order lines where
    # product_id is None but impa_code is set.
    # (OrderItem.product_id is nullable in IMPA-first mode;
    #  QuoteItem.product_id is NOT NULL, so we must resolve.)
    impa_to_product: dict[str, UUID] = {}
    need_lookup = [ri for ri in rfq.items if ri.product_id is None and ri.impa_code]
    if need_lookup:
        from app.models.product import ImpaCode, Product
        impa_codes = {ri.impa_code for ri in need_lookup}
        rows = (await db.execute(
            select(Product.id, ImpaCode.code)
            .join(ImpaCode, ImpaCode.id == Product.impa_code_id)
            .where(ImpaCode.code.in_(impa_codes))
        )).all()
        impa_to_product = {code: pid for pid, code in rows}

    # Process line items
    subtotal = 0.0
    quote_items: list[QuoteItem] = []
    for line in lines:
        rid = line.get("rfq_item_id")
        status = line.get("line_status", "full")
        ri = rfq_items.get(str(rid)) if rid else None
        if ri is None:
            raise ValueError(f"Unknown rfq_item_id: {rid}")
        # IMPA-first order lines may have no product_id; resolve via impa_code
        resolved_product_id = ri.product_id or impa_to_product.get(ri.impa_code)
        if resolved_product_id is None:
            raise ValueError(
                f"RFQ item {rid} has no product_id and cannot resolve impa_code={ri.impa_code!r}"
            )
        if status not in ("full", "partial", "none"):
            raise ValueError(f"Invalid line_status: {status}")

        if status == "none":
            # No-bid line
            quote_items.append(QuoteItem(
                product_id=resolved_product_id,
                quantity=ri.quantity,
                unit_price=0,
                line_total=0,
                line_status="none",
                quoted_quantity=0,
            ))
            continue

        unit_price = float(line["unit_price"])
        if status == "partial":
            qty = int(line.get("quoted_quantity") or 0)
            if qty <= 0 or qty > ri.quantity:
                raise ValueError(
                    f"Partial quoted_quantity {qty} out of range for rfq_item {rid}"
                )
        else:
            qty = ri.quantity

        line_total = round(qty * unit_price, 4)
        subtotal += line_total
        quote_items.append(QuoteItem(
            product_id=resolved_product_id,
            quantity=qty,
            unit_price=unit_price,
            line_total=line_total,
            line_status=status,
            quoted_quantity=qty if status == "partial" else None,
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
        valid_until=_now() + timedelta(days=14),
        marked_up_total=round(subtotal, 4),  # Initially same as total (markup = 0)
        customer_facing_total=round(subtotal, 4),
        items=quote_items,
    )

    rfq.responded_count += 1
    db.add(quote)
    return quote


async def apply_markup(
    db: AsyncSession,
    rfq: RFQ,
    *,
    markup_pct: float,
) -> RFQ:
    """Apply a uniform markup percentage to ALL quotes in the RFQ.

    Updates rfq.markup_pct and each quote's marked_up_total and
    customer_facing_total.
    """
    if rfq.status != RFQStatus.SENT:
        raise ValueError(f"RFQ is {rfq.status.value}; expected SENT")
    if not (0 <= markup_pct <= 100):
        raise ValueError(f"markup_pct {markup_pct} out of range [0, 100]")

    rfq.markup_pct = markup_pct

    # Update all quotes with the markup
    quotes = (await db.execute(
        select(SupplierQuote).where(SupplierQuote.rfq_id == rfq.id)
    )).scalars().all()

    for quote in quotes:
        quote.marked_up_total = round(quote.total * (1 + markup_pct / 100), 4)
        quote.customer_facing_total = quote.marked_up_total

    return rfq


async def send_to_purchaser(
    db: AsyncSession,
    rfq: RFQ,
) -> RFQ:
    """Mark RFQ as CLOSED (ready for purchaser review).

    The admin calls this after applying markup and reviewing quotes.
    """
    if rfq.status != RFQStatus.SENT:
        raise ValueError(f"RFQ is {rfq.status.value}; expected SENT")

    rfq.status = RFQStatus.CLOSED
    rfq.closed_at = _now()

    # Update order status
    order = (await db.execute(
        select(Order).where(Order.id == rfq.order_id)
    )).scalar_one_or_none()
    if order is not None:
        order.status = OrderStatus.RFQ_CLOSED

    return rfq


async def purchaser_decide(
    db: AsyncSession,
    rfq: RFQ,
    *,
    approve: bool,
    reason: str | None,
) -> dict[str, Any]:
    """Purchaser approves or rejects the entire proposal.

    On approve:
      - RFQ -> AWARDED
      - Order -> APPROVED
    On reject:
      - RFQ -> CANCELLED
      - Order -> DRAFT
    """
    if rfq.status != RFQStatus.CLOSED:
        raise ValueError(f"RFQ is {rfq.status.value}; expected CLOSED")

    order = (await db.execute(
        select(Order).where(Order.id == rfq.order_id)
    )).scalar_one_or_none()
    if order is None:
        raise ValueError(f"Order {rfq.order_id} not found")

    if not approve:
        rfq.status = RFQStatus.CANCELLED
        order.status = OrderStatus.DRAFT
        order.rejection_reason = reason
        return {
            "order_id": str(order.id),
            "rfq_id": str(rfq.id),
            "status": order.status.value,
            "rfq_status": rfq.status.value,
            "message": "Order returned to DRAFT. You can edit and re-submit.",
        }

    # Approve
    rfq.status = RFQStatus.AWARDED
    rfq.awarded_at = _now()

    # Find the "best" quote (could be extended with scoring logic)
    # For now, just pick the first quote as the awarded one
    quotes = (await db.execute(
        select(SupplierQuote).where(SupplierQuote.rfq_id == rfq.id)
    )).scalars().all()
    if quotes:
        rfq.awarded_quote_id = quotes[0].id

    order.status = OrderStatus.APPROVED
    order.approved_at = _now()
    order.approved_by = order.created_by  # Purchaser is typically the creator

    return {
        "order_id": str(order.id),
        "rfq_id": str(rfq.id),
        "status": order.status.value,
        "rfq_status": rfq.status.value,
        "message": "Order approved and awarded.",
    }


async def get_quotes_for_purchaser(
    db: AsyncSession,
    rfq: RFQ,
) -> list[dict[str, Any]]:
    """Get all quotes for an RFQ with markup applied, for purchaser view.

    Returns simplified view without supplier identity (for fairness).
    """
    quotes = (await db.execute(
        select(SupplierQuote)
        .where(SupplierQuote.rfq_id == rfq.id)
        .order_by(SupplierQuote.submitted_at)
    )).scalars().all()

    result = []
    for quote in quotes:
        # Anonymize supplier info for purchaser
        supplier = await db.get(Supplier, quote.supplier_id)
        result.append({
            "quote_id": str(quote.id),
            "reference": quote.reference,
            "subtotal": float(quote.subtotal),
            "total": float(quote.total),
            "marked_up_total": float(quote.marked_up_total),
            "customer_facing_total": float(quote.customer_facing_total),
            "lead_time_days": quote.lead_time_days,
            "payment_terms": quote.payment_terms,
            "notes": quote.notes,
            "submitted_at": quote.submitted_at.isoformat(),
            # Supplier identity is hidden from purchaser
            "supplier_alias": f"Supplier {quote.id.hex[:4].upper()}",
            "items": [
                {
                    "product_id": str(item.product_id),
                    "quantity": item.quantity,
                    "unit_price": float(item.unit_price),
                    "line_total": float(item.line_total),
                    "line_status": item.line_status,
                    "quoted_quantity": item.quoted_quantity,
                }
                for item in quote.items
            ],
        })
    return result


async def _load_order(db: AsyncSession, order_id: UUID) -> Order | None:
    return (await db.execute(
        select(Order).where(Order.id == order_id)
    )).scalar_one_or_none()
# Simplified marketplace flow — filled (backup only; for_git untouched)
# Attribution: Co-Authored-By: Claude Code <noreply@anthropic.com>
# 🤖 Generated with [Claude Code](https://claude.com/claude-code)

# Co-Authored-By: Claude Code <noreply@anthropic.com>
# 🤖 Generated with [Claude Code](https://claude.com/claude-code)

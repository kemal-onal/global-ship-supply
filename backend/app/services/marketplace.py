"""Marketplace service — the fan-out / decision / approval flow.

Replaces the sealed-bid bid war (see ``market_sim.py``). The flow:

  1. fan_out_rfq
       - refuse to fire if there's an open clarification
       - snapshot the vessel's ETA for the destination port
       - copy the order's items into RFQItems
       - invite every ACTIVE supplier at the port (no cap, no
         per-product filter — suppliers can return "none" for what
         they don't carry)
       - mark the order QUOTING

  2. supplier_submit_quote
       - one quote per (rfq, supplier) — re-submission overwrites
         the previous quote (the bidder rethinks their offer)
       - per-line: full / partial / none
       - if "partial", quoted_quantity = ceil(requested / 2)
       - increment rfq.responded_count
       - if responded_count == invited_count, mark the RFQ
         READY_FOR_COMPOSE so the company can proceed

  3. compose_proposal
       - admin posts a list of decisions: (rfq_item_id, supplier_id, decision)
       - one OrderDecision per use_full / use_half
       - drop is implicit (no row written for that line)
       - the order's company_margin_pct is applied per line to
         produce customer_facing_total
       - order moves to AWAITING_PURCHASER_APPROVAL

  4. purchaser_approve_proposal
       - approve: order -> CONFIRMED, create SupplierLineAssignment
         rows for every decision with preparation_deadline = now + 24h,
         notify the winning suppliers
       - reject: order -> REJECTED with a reason

  5. supplier_accept_slice
       - supplier clicks "accept" on their slice within 24h
       - sets confirmed_at on the assignment

  6. drop_slow_supplier
       - flips an assignment's line_status to "dropped"
       - sets dropped_at, drop_reason
       - the line goes back to "needs another supplier" state; no
         auto re-bid (the company has to invite another)

The bid war engine (``market_sim.py``) and the
``market_sim_events`` table stay untouched. Any future demo can
revive them via ``POST /api/v1/rfq/{id}/simulate`` — but no UI
points to that path now.

Identity sealing is handled by ``app.services.redaction`` (the
existing 3-tier redaction). Purchaser-facing views drop the
supplier_id and unit_price; supplier-facing views drop the
vessel's real name.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.ais import AisPositionReport
from app.models.notification import NotificationType
from app.models.order import Order, OrderItem, OrderStatus
from app.models.product import Product
from app.models.supplier import (
    AssignmentStatus,
    OrderDecision,
    QuoteItem,
    RFQ,
    RFQItem,
    RFQStatus,
    Supplier,
    SupplierLineAssignment,
    SupplierPort,
    SupplierQuote,
    SupplierStatus,
)
from app.models.user import Role, UserRole
from app.models.vessel import Vessel
from app.services import clarification as clarification_svc
from app.services.notifications import create_notification


# 24 hours from proposal approval. Suppliers who don't click
# "accept" inside this window get dropped (see
# ``drop_slow_supplier``).
PREPARATION_WINDOW = timedelta(hours=24)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ──────────────────────────────────────────────────────────────────
# Step 1: fan out the RFQ to every active supplier at the port
# ──────────────────────────────────────────────────────────────────


async def fan_out_rfq(
    db: AsyncSession,
    order: Order,
    *,
    response_deadline_hours: int | None = None,
) -> RFQ:
    """Build the RFQ and invite every ACTIVE supplier at the port.

    Refuses to fire while there's an open clarification question.
    Snapshots the order's ETA before returning. The order moves
    to ``QUOTING`` and the RFQ to ``SENT``.

    Note: the existing ``build_rfq_for_order`` in
    ``app.services.rfq`` keeps the legacy "only suppliers that
    cover the products in the order" rule for the bid war flow.
    The marketplace flow uses THIS function instead, which is
    intentionally wider (suppliers can return "none" per line).
    """
    if clarification_svc.has_unresolved_clarifications(order):
        raise ValueError(
            "Cannot fan out while there are unresolved clarification questions"
        )
    if order.status not in (OrderStatus.DRAFT, OrderStatus.AWAITING_CLARIFICATION):
        raise ValueError(
            f"Cannot fan out from status {order.status.value}; expected DRAFT or AWAITING_CLARIFICATION"
        )

    # ETA + ETD snapshot — the marketplace UI surfaces this for the
    # "lead time vs ETA" warning, and the supplier uses the
    # [eta_at_port, etd_at_port] window to decide whether they can
    # deliver the package in time. We snapshot regardless of whether
    # the AIS data is fresh; a null result becomes a "no recent
    # AIS" warning in the lattice / supplier portal.
    try:
        from app.services.eta import write_eta_to_order, write_etd_to_order
        await write_eta_to_order(db, order)
        await write_etd_to_order(db, order)
    except Exception:
        # ETA/ETD snapshot failures are advisory; the flow proceeds
        # without them. The UI shows the warning.
        pass

    deadline_h = response_deadline_hours or settings.RFQ_RESPONSE_TIMEOUT_HOURS
    rfq = RFQ(
        reference=_new_reference("RFQ"),
        order_id=order.id,
        port_id=order.port_id,
        status=RFQStatus.SENT,
        sent_at=_now(),
        response_deadline=_now() + timedelta(hours=deadline_h),
    )
    # Copy line items. The rfq_item.description is sourced from
    # OrderItem.notes (the marketplace redesign's "intended use"
    # field lives in OrderItem.notes; see app.api.v1.orders).
    for oi in order.items:
        rfq.items.append(RFQItem(
            product_id=oi.product_id,
            quantity=oi.quantity,
            unit=oi.unit,
            # The order's unit_price is always 0 in the IMPA-first
            # redesign (the order carries no price). We still write
            # the column for legacy compatibility; the lattice and
            # proposal surfaces derive the price from the supplier's
            # quote, not from the order.
            target_unit_price=oi.unit_price,
            description=oi.notes,
            # IMPA-first redesign: the typed IMPA code the purchaser
            # supplied lives on order_items.impa_code. The supplier
            # sees this on the RFQ detail (it's the source of truth
            # for what was ordered). Legacy RFQs (built before the
            # column existed) may have a product_id but no impa_code
            # — the supplier's portal falls back to the product's
            # IMPA code in that case via the legacy backfill below.
            impa_code=oi.impa_code,
        ))

    db.add(rfq)
    await db.flush()  # need rfq.id + rfq_item ids

    # Legacy backfill: for rfq_items where impa_code is still null
    # (the order had a product_id but no typed IMPA — pre-IMPA-first
    # rows), pull the IMPA code from the product. This keeps the
    # supplier portal's display "IMPA 632121" intact for legacy RFQs.
    needs_backfill = [ri for ri in rfq.items if not ri.impa_code and ri.product_id]
    if needs_backfill:
        product_ids = {ri.product_id for ri in needs_backfill}
        from app.models.product import ImpaCode
        impa_rows = (await db.execute(
            select(Product.id, ImpaCode.code)
            .join(ImpaCode, ImpaCode.id == Product.impa_code_id)
            .where(Product.id.in_(product_ids))
        )).all()
        impa_map = {pid: code for pid, code in impa_rows}
        for ri in needs_backfill:
            ri.impa_code = impa_map.get(ri.product_id)

    # Find every active supplier at the port. The marketplace
    # redesign fans out wide (no product coverage filter) — a
    # supplier can return "none" for products they don't carry.
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
    order.status = OrderStatus.QUOTING

    return rfq


# ──────────────────────────────────────────────────────────────────
# Step 2: a supplier submits a quote
# ──────────────────────────────────────────────────────────────────


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
    can_deliver_in_window: bool | None = None,
    decline_reason: str | None = None,
) -> SupplierQuote:
    """Supplier's per-line answer (full / partial / none).

    ``lines`` shape:
      [
        {
          "rfq_item_id":    "<uuid>",
          "line_status":    "full" | "partial" | "none",
          "unit_price":     float (required for full/partial),
          "quoted_quantity": int  (optional; defaults to ceil(req/2) for partial)
        },
        ...
      ]

    IMPA-first redesign (migration 0007): the supplier's
    ETA/ETD gate runs *before* the line picker. ``can_deliver_in_window``
    is one of:

      * ``None``  — not yet decided. The line picker must be empty
        and the quote is NOT counted toward ``responded_count``.
        The lattice hides it.
      * ``True``  — the supplier can deliver between ETA and ETD.
        The line picker opens and the supplier fills in
        ``lines``. The quote is counted.
      * ``False`` — the supplier declined. ``decline_reason`` is
        optional. The quote is created with no items, the lattice
        shows "declined" for this supplier, and the quote is
        counted toward ``responded_count`` so the RFQ can still
        progress to compose.

    The supplier may omit lines entirely (a "no bid" on the whole
    RFQ); in that case we still create a SupplierQuote row with
    no items, so the company sees a "no-bid" cell in the lattice.

    Re-submission overwrites the previous quote for the same
    (rfq, supplier). The previous SupplierQuote's id is lost
    (no history kept) — the supplier sees the latest one in
    their portal.
    """
    if rfq.status not in (RFQStatus.SENT, RFQStatus.OPEN):
        raise ValueError(f"RFQ is {rfq.status.value}; cannot accept quotes")
    if _now() > rfq.response_deadline:
        raise ValueError("RFQ response deadline passed")
    if supplier.status != SupplierStatus.ACTIVE:
        raise ValueError("Supplier not active")

    # Map rfq_item_ids to their target quantity/unit, so we can
    # validate "partial" quantities and compute totals.
    rfq_items = {str(ri.id): ri for ri in rfq.items}
    # Drop the existing quote if any (re-submission).
    existing = (await db.execute(
        select(SupplierQuote).where(
            SupplierQuote.rfq_id == rfq.id,
            SupplierQuote.supplier_id == supplier.id,
        )
    )).scalar_one_or_none()
    if existing is not None:
        await db.delete(existing)
        await db.flush()
        # Decrement the responded_count so the new submission
        # still counts. If the new quote brings responded_count
        # to invited_count, the RFQ flips to READY_FOR_COMPOSE.
        # Skip if the prior quote was a "not yet decided" gate
        # state (it didn't count toward responded_count).
        if existing.can_deliver_in_window is not None:
            rfq.responded_count = max(0, rfq.responded_count - 1)

    # --- IMPA-first gate validation -------------------------------
    # A "no decision" submission must carry no lines. A declined
    # submission may carry no lines. Only a "yes" submission is
    # required to have lines.
    if can_deliver_in_window is None:
        # Not yet decided — the supplier hasn't clicked anything.
        # The line picker is not open yet; the quote is "in
        # progress" and doesn't count toward responded_count.
        if lines:
            raise ValueError(
                "Cannot submit line prices without a can_deliver_in_window decision"
            )
        # Persist a placeholder quote so the supplier portal can
        # show the gate as "in progress" rather than "not started".
        quote = SupplierQuote(
            rfq_id=rfq.id,
            supplier_id=supplier.id,
            order_id=rfq.order_id,
            reference=_new_reference("Q"),
            subtotal=0,
            tax=0,
            shipping=0,
            total=0,
            lead_time_days=lead_time_days,
            payment_terms=payment_terms,
            notes=notes,
            source=source,
            valid_until=_now() + timedelta(days=14),
            decision_method=None,
            can_deliver_in_window=None,
            declined_at=None,
            decline_reason=None,
            items=[],
        )
        db.add(quote)
        return quote

    # --- A "yes" or "no" decision was made ------------------------
    if can_deliver_in_window is False:
        # Declined: store the gate flag + reason, no line items.
        # Counted toward responded_count so the RFQ can progress.
        if not isinstance(decline_reason, str) or not decline_reason.strip():
            # decline_reason is optional but if provided must be a
            # non-empty string. We don't enforce required here.
            pass
        quote = SupplierQuote(
            rfq_id=rfq.id,
            supplier_id=supplier.id,
            order_id=rfq.order_id,
            reference=_new_reference("Q"),
            subtotal=0,
            tax=0,
            shipping=0,
            total=0,
            lead_time_days=lead_time_days,
            payment_terms=payment_terms,
            notes=notes,
            source=source,
            valid_until=_now() + timedelta(days=14),
            decision_method=None,
            can_deliver_in_window=False,
            declined_at=_now(),
            decline_reason=(decline_reason or "").strip() or None,
            items=[],
        )
        rfq.responded_count += 1
        if rfq.responded_count >= rfq.invited_count:
            rfq.status = RFQStatus.CLOSED
            order = await _load_order(db, rfq.order_id)
            if order is not None and order.status == OrderStatus.QUOTING:
                order.status = OrderStatus.READY_FOR_COMPOSE
        db.add(quote)
        return quote

    # can_deliver_in_window is True — the supplier is in.
    subtotal = 0.0
    quote_items: list[QuoteItem] = []
    decision_method: str | None = None
    for line in lines:
        rid = line.get("rfq_item_id")
        status = line.get("line_status", "full")
        ri = rfq_items.get(str(rid)) if rid else None
        if ri is None:
            raise ValueError(f"Unknown rfq_item_id: {rid}")
        if status not in ("full", "partial", "none"):
            raise ValueError(f"Invalid line_status: {status}")

        if status == "none":
            # No-bid line. Still a row, so the company sees the
            # "no-bid" cell in the lattice.
            quote_items.append(QuoteItem(
                product_id=ri.product_id,
                quantity=ri.quantity,
                unit_price=0,
                line_total=0,
                line_status="none",
                quoted_quantity=0,
            ))
            continue

        unit_price = float(line["unit_price"])
        if status == "partial":
            qty = int(line.get("quoted_quantity") or math.ceil(ri.quantity / 2))
            if qty <= 0 or qty > ri.quantity:
                raise ValueError(
                    f"Partial quoted_quantity {qty} out of range for rfq_item {rid}"
                )
        else:
            qty = ri.quantity
        line_total = round(qty * unit_price, 4)
        subtotal += line_total
        quote_items.append(QuoteItem(
            product_id=ri.product_id,
            quantity=qty,
            unit_price=unit_price,
            line_total=line_total,
            line_status=status,
            quoted_quantity=qty,
        ))
        # Track the supplier's overall decision shape: "full" if
        # every non-none line was full, "partial" if at least one
        # was partial. Used to filter / badge in the lattice.
        if status == "partial" and decision_method != "partial":
            decision_method = "partial"
        elif decision_method is None:
            decision_method = "full"

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
        decision_method=decision_method,
        can_deliver_in_window=True,
        declined_at=None,
        decline_reason=None,
        items=quote_items,
    )
    rfq.responded_count += 1
    if rfq.responded_count >= rfq.invited_count:
        rfq.status = RFQStatus.CLOSED
        # Order moves to READY_FOR_COMPOSE so the company knows
        # they can proceed. Deadline-based auto-progress is a
        # background task (see prepare_deadline_sweeper).
        order = await _load_order(db, rfq.order_id)
        if order is not None and order.status == OrderStatus.QUOTING:
            order.status = OrderStatus.READY_FOR_COMPOSE
    db.add(quote)
    return quote


# ──────────────────────────────────────────────────────────────────
# Step 3: company composes the proposal
# ──────────────────────────────────────────────────────────────────


async def compose_proposal(
    db: AsyncSession,
    rfq: RFQ,
    *,
    decisions: list[dict[str, Any]],
    margin_pct: float,
    composed_by: UUID,
) -> list[OrderDecision]:
    """Per-line decision: which supplier's offer are we using?

    ``decisions`` shape:
      [
        {
          "rfq_item_id": "<uuid>",
          "supplier_id": "<uuid>",
          "quote_id":    "<uuid>",
          "decision":    "use_full" | "use_half" | "drop"
        },
        ...
      ]

    For each use_full / use_half entry, write an OrderDecision
    carrying the supplier's unit_price, the used quantity, and
    the customer_facing_total (with margin applied). Drop is
    implicit — no row written for the dropped line.

    The order moves to AWAITING_PURCHASER_APPROVAL. The purchaser
    sees the composed proposal (per-line totals with margin
    applied, lead time, payment terms) but no supplier names.
    """
    if rfq.status not in (RFQStatus.SENT, RFQStatus.OPEN, RFQStatus.CLOSED):
        raise ValueError(
            f"RFQ is {rfq.status.value}; cannot compose proposal"
        )
    if not (0 <= margin_pct <= 100):
        raise ValueError(f"margin_pct {margin_pct} out of range [0, 100]")

    order = await _load_order(db, rfq.order_id)
    if order is None:
        raise ValueError(f"Order {rfq.order_id} not found")
    if order.status not in (OrderStatus.QUOTING, OrderStatus.READY_FOR_COMPOSE):
        raise ValueError(
            f"Order is {order.status.value}; cannot compose proposal"
        )

    # Wipe any prior decisions (re-composing). Cascade-deletes
    # SupplierLineAssignment rows via FK.
    existing = (await db.execute(
        select(OrderDecision).where(OrderDecision.order_id == order.id)
    )).scalars().all()
    for d in existing:
        await db.delete(d)
    await db.flush()

    # Look up the relevant quote items once so we can compute
    # used_quantity + line_total.
    rfq_items = {str(ri.id): ri for ri in rfq.items}
    decision_rows: list[OrderDecision] = []
    for d in decisions:
        if d["decision"] == "drop":
            continue  # implicit — no row written
        if d["decision"] not in ("use_full", "use_half"):
            raise ValueError(f"Invalid decision: {d['decision']}")
        ri = rfq_items.get(str(d["rfq_item_id"]))
        if ri is None:
            raise ValueError(f"Unknown rfq_item_id: {d['rfq_item_id']}")
        # The supplier's unit_price for this line is on the quote.
        qi = (await db.execute(
            select(QuoteItem)
            .where(
                QuoteItem.quote_id == d["quote_id"],
                QuoteItem.product_id == ri.product_id,
            )
        )).scalar_one_or_none()
        if qi is None:
            raise ValueError(
                f"No quote_item for quote {d['quote_id']} product {ri.product_id}"
            )
        used_qty = qi.quoted_quantity if d["decision"] == "use_half" else ri.quantity
        # The supplier's offer may itself be partial. use_half on a
        # partial offer takes half the partial quantity.
        if d["decision"] == "use_half":
            used_qty = math.ceil(used_qty / 2)
        unit_price = float(qi.unit_price)
        line_total = round(unit_price * used_qty, 4)
        customer_facing_total = round(line_total * (1 + margin_pct / 100), 4)
        decision_rows.append(OrderDecision(
            order_id=order.id,
            rfq_item_id=ri.id,
            supplier_id=d["supplier_id"],
            quote_id=d["quote_id"],
            decision=d["decision"],
            unit_price=unit_price,
            used_quantity=used_qty,
            line_total=line_total,
            margin_pct=margin_pct,
            customer_facing_total=customer_facing_total,
            created_by=composed_by,
        ))

    for row in decision_rows:
        db.add(row)
    order.company_margin_pct = margin_pct
    order.status = OrderStatus.AWAITING_PURCHASER_APPROVAL
    return decision_rows


# ──────────────────────────────────────────────────────────────────
# Step 4: purchaser approves or rejects
# ──────────────────────────────────────────────────────────────────


async def purchaser_approve_proposal(
    db: AsyncSession,
    order: Order,
    *,
    approve: bool,
    reason: str | None,
    actor_id: UUID,
) -> dict[str, Any]:
    """Approve the composed proposal.

    On approve:
      - order -> CONFIRMED
      - one SupplierLineAssignment per OrderDecision, with
        preparation_deadline = now + 24h and line_status = "pending"
      - notify each winning supplier

    On reject:
      - order -> REJECTED with the reason
    """
    if order.status != OrderStatus.AWAITING_PURCHASER_APPROVAL:
        raise ValueError(
            f"Order is {order.status.value}; expected AWAITING_PURCHASER_APPROVAL"
        )
    decisions = (await db.execute(
        select(OrderDecision).where(OrderDecision.order_id == order.id)
    )).scalars().all()
    if not decisions:
        raise ValueError("No decisions to approve")

    if not approve:
        order.status = OrderStatus.REJECTED
        order.rejection_reason = reason
        return {"order_id": str(order.id), "status": order.status.value, "assignments_created": 0}

    now = _now()
    deadline = now + PREPARATION_WINDOW
    created: list[SupplierLineAssignment] = []
    for d in decisions:
        sla = SupplierLineAssignment(
            order_id=order.id,
            rfq_item_id=d.rfq_item_id,
            supplier_id=d.supplier_id,
            quote_id=d.quote_id,
            decision_id=d.id,
            line_status=AssignmentStatus.PENDING.value,
            preparation_deadline=deadline,
        )
        db.add(sla)
        created.append(sla)
    order.status = OrderStatus.CONFIRMED

    # Notify each winning supplier. The notification service
    # writes one row per (user, notification). Suppliers are
    # represented as users (the supplier user has the
    # ``supplier`` role); we look up the supplier's user by
    # company_name match — supplier.contact_email is the user
    # email. (See scripts.seed.py — the supplier@apcmarine.sg
    # account is bound to APC Marine by contact_email.)
    await db.flush()  # so sla.id is populated for the data payload
    supplier_ids = list({d.supplier_id for d in decisions})
    from app.models.user import User
    suppliers = (await db.execute(
        select(Supplier).where(Supplier.id.in_(supplier_ids))
    )).scalars().all()
    contact_emails = [s.contact_email for s in suppliers]
    users = (await db.execute(
        select(User).where(User.email.in_(contact_emails))
    )).scalars().all()
    email_to_user = {u.email: u for u in users}
    for s in suppliers:
        u = email_to_user.get(s.contact_email)
        if u is None:
            continue
        await create_notification(
            db,
            user_id=u.id,
            type=NotificationType.SLICE_ASSIGNED,
            title=f"Order {order.reference} — please confirm preparation",
            body=(
                f"You have slices on order {order.reference} that need "
                f"confirmation by {deadline.isoformat()}."
            ),
            data={
                "order_id": str(order.id),
                "preparation_deadline": deadline.isoformat(),
                "supplier_id": str(s.id),
            },
        )
    return {
        "order_id": str(order.id),
        "status": order.status.value,
        "assignments_created": len(created),
        "preparation_deadline": deadline.isoformat(),
    }


# ──────────────────────────────────────────────────────────────────
# Step 5: supplier accepts a slice within 24h
# ──────────────────────────────────────────────────────────────────


async def supplier_accept_slice(
    db: AsyncSession,
    supplier: Supplier,
    assignment: SupplierLineAssignment,
) -> SupplierLineAssignment:
    """Supplier clicks "accept" on a slice before its deadline."""
    if assignment.supplier_id != supplier.id:
        raise ValueError("Assignment does not belong to this supplier")
    if assignment.line_status != AssignmentStatus.PENDING.value:
        raise ValueError(
            f"Assignment is {assignment.line_status}; cannot accept"
        )
    if assignment.preparation_deadline and _now() > assignment.preparation_deadline:
        # The 24h window has closed. The next sweep will pick
        # this up; we just refuse the accept now.
        raise ValueError("Preparation deadline has passed")
    assignment.line_status = AssignmentStatus.CONFIRMED.value
    assignment.confirmed_at = _now()
    return assignment


# ──────────────────────────────────────────────────────────────────
# Step 6: drop a slow supplier (manual or auto)
# ──────────────────────────────────────────────────────────────────


async def drop_slow_supplier(
    db: AsyncSession,
    assignment: SupplierLineAssignment,
    *,
    reason: str = "preparation_timeout_24h",
) -> SupplierLineAssignment:
    """Mark an assignment as dropped.

    Called by:
      * the 24h preparation timeout sweeper (auto)
      * the admin's manual "drop supplier" button (manual)

    The line goes back to "needs another supplier" state. The
    flow does NOT auto re-bid — the company has to invite
    another supplier. This is by design: a dropped slice
    shouldn't trigger a second fan-out; the company knows the
    context and picks.
    """
    if assignment.line_status != AssignmentStatus.PENDING.value:
        raise ValueError(
            f"Assignment is {assignment.line_status}; cannot drop"
        )
    assignment.line_status = AssignmentStatus.DROPPED.value
    assignment.dropped_at = _now()
    assignment.drop_reason = reason
    return assignment


# ──────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────


def _new_reference(prefix: str) -> str:
    return f"{prefix}-{_now().strftime('%Y%m%d-%H%M%S')}-{uuid_short()}"


def uuid_short() -> str:
    """Return a short hex token (8 chars) for human-readable refs."""
    import uuid as _uuid
    return _uuid.uuid4().hex[:8]


async def _load_order(db: AsyncSession, order_id: UUID) -> Order | None:
    return (await db.execute(
        select(Order).where(Order.id == order_id)
    )).scalar_one_or_none()


# ──────────────────────────────────────────────────────────────────
# Background sweeps — preparation timeouts and deadline progress
# ──────────────────────────────────────────────────────────────────


async def sweep_preparation_timeouts(db: AsyncSession) -> dict[str, int]:
    """Drop assignments whose 24h window has expired.

    Called by the asyncio background task started in ``app.main``
    lifespan; runs every 5 minutes. Returns a small summary
    (counts only — the rows themselves are the audit trail).
    """
    now = _now()
    expired = (await db.execute(
        select(SupplierLineAssignment)
        .where(
            SupplierLineAssignment.line_status == AssignmentStatus.PENDING.value,
            SupplierLineAssignment.preparation_deadline.isnot(None),
            SupplierLineAssignment.preparation_deadline < now,
        )
    )).scalars().all()
    dropped = 0
    for sla in expired:
        try:
            await drop_slow_supplier(db, sla, reason="preparation_timeout_24h")
            dropped += 1
        except ValueError:
            # Race with a manual confirm — skip silently.
            continue
    if dropped:
        await db.commit()
    return {"expired_seen": len(expired), "dropped": dropped}


async def sweep_rfq_deadlines(db: AsyncSession) -> dict[str, int]:
    """Move RFQs whose response deadline has passed into READY_FOR_COMPOSE.

    Without this, an RFQ would stay QUOTING forever if not all
    invited suppliers respond before the deadline. The supplier
    is already past the deadline — we just flip the status so
    the company can proceed with what they have.
    """
    now = _now()
    expired = (await db.execute(
        select(RFQ)
        .where(
            RFQ.status == RFQStatus.SENT,
            RFQ.response_deadline < now,
        )
    )).scalars().all()
    progressed = 0
    for rfq in expired:
        rfq.status = RFQStatus.CLOSED
        order = await _load_order(db, rfq.order_id)
        if order is not None and order.status == OrderStatus.QUOTING:
            order.status = OrderStatus.READY_FOR_COMPOSE
        progressed += 1
    if progressed:
        await db.commit()
    return {"expired_seen": len(expired), "progressed": progressed}

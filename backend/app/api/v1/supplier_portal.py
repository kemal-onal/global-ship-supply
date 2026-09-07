"""Supplier portal routes — the supplier-facing API.

The supplier is authenticated as a regular user (the
``supplier@apcmarine.sg`` account in the demo seed). We resolve
them to a ``Supplier`` row by matching the user's email to
``Supplier.contact_email``. No vessel scope applies here — a
supplier doesn't belong to a vessel.

Routes:
  GET   /api/v1/supplier-portal/rfqs                  [supplier]
  GET   /api/v1/supplier-portal/rfqs/{rfq_id}         [supplier]
  POST  /api/v1/supplier-portal/rfqs/{rfq_id}/quote   [supplier]
  POST  /api/v1/supplier-portal/quotes/{quote_id}/accept  [supplier]
  GET   /api/v1/supplier-portal/assignments           [supplier]

Vessel anonymization: in the marketplace redesign, the supplier
shouldn't see the vessel's real name. The route still uses the
existing 3-tier redaction (``hides_prices`` +
``seal_order_for_supplier``) so the supplier's RFQ detail shows
"Vessel #N" instead of the actual vessel.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.deps.auth import (
    CurrentToken,
    DBSession,
    ReadDBSession,
    require_permission,
)
from app.models.audit import AuditAction, AuditLog
from app.models.order import Order
from app.models.supplier import (
    RFQ,
    RFQItem,
    RFQStatus,
    Supplier,
    SupplierLineAssignment,
    SupplierQuote,
)
from app.models.user import User
from app.services import marketplace as marketplace_svc

router = APIRouter(prefix="/supplier-portal", tags=["supplier-portal"])


# ── Helpers ────────────────────────────────────────────────────────


async def _load_supplier_for_token(db, token) -> Supplier:
    """Resolve the caller's Supplier row via their user email.

    A supplier user is matched by ``User.email == Supplier.contact_email``.
    If the user has the ``supplier`` role but no matching supplier row,
    we 403 — that means the account is misconfigured.
    """
    user = (await db.execute(
        select(User).where(User.id == token.sub)
    )).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="Unknown user")
    supplier = (await db.execute(
        select(Supplier).where(Supplier.contact_email == user.email)
    )).scalar_one_or_none()
    if supplier is None:
        raise HTTPException(
            status_code=403,
            detail="No supplier profile bound to this user account",
        )
    return supplier


def _anonymize_vessel_name(order: Order) -> str | None:
    """Return a stable, anonymized label for the order's vessel.

    We use a CRC32 of the vessel id so the same vessel always
    shows up as the same "Vessel #N" across the supplier's
    multiple RFQs. This matches the sealed-bid redaction style
    used elsewhere in the app.
    """
    import zlib
    if order.vessel_id is None:
        return None
    h = zlib.crc32(str(order.vessel_id).encode("utf-8")) % 1000
    return f"Vessel #{h}"


# ── Schemas ────────────────────────────────────────────────────────


class QuoteLineIn(BaseModel):
    rfq_item_id: str
    line_status: str = Field(pattern="^(full|partial|none)$")
    unit_price: float | None = Field(default=None, ge=0)
    quoted_quantity: int | None = Field(default=None, ge=0)


class QuoteIn(BaseModel):
    # IMPA-first gate (migration 0007): the supplier decides
    # "can I deliver the whole package between ETA and ETD"
    # *before* filling in any line prices. The lead time is
    # only required once the supplier opens the line picker
    # (can_deliver_in_window=True and lines are non-empty).
    # For a pure yes/no gate click we don't have one yet, so
    # accept None and let the service fall back to the model's
    # default (7 days). Validation (ge=1, le=180) only kicks
    # in when a value is provided.
    lead_time_days: int | None = Field(default=None, ge=1, le=180)
    payment_terms: str | None = None
    notes: str | None = None
    source: str = "portal"
    # None = not yet decided (the line picker is closed).
    # True = supplier is in (lines required below).
    # False = supplier declined (lines ignored; decline_reason
    # recorded).
    can_deliver_in_window: bool | None = None
    decline_reason: str | None = None
    lines: list[QuoteLineIn] = []


# ── Routes ─────────────────────────────────────────────────────────


@router.get("/rfqs")
async def list_rfqs(
    db: ReadDBSession,
    token: Annotated[CurrentToken, Depends(require_permission("supplier_portal", "view", "global"))],
    status: RFQStatus | None = None,
    limit: int = 50,
    offset: int = 0,
):
    """List RFQs the calling supplier is invited to.

    The marketplace redesign stores the invited supplier ids on
    ``rfqs.extra->'invited_supplier_ids'`` (JSONB). We filter
    on that. The bid war's RFQ list (no extras) is left as
    legacy; the supplier portal is marketplace-only.
    """
    supplier = await _load_supplier_for_token(db, token)
    # Eager-load the order's vessel for anonymization, plus
    # the quotes so the per-RFQ `has_quote` / `quote_id`
    # computation below doesn't trigger an implicit lazy load
    # on `r.quotes` (which would explode with MissingGreenlet
    # in this async session). The per-RFQ endpoint at line ~193
    # already does this; the list endpoint just forgot to.
    stmt = (
        select(RFQ)
        .options(
            selectinload(RFQ.items),
            selectinload(RFQ.order),
            selectinload(RFQ.quotes),
        )
        .order_by(RFQ.sent_at.desc())
    )
    if status is not None:
        stmt = stmt.where(RFQ.status == status)
    rows = (await db.execute(stmt.limit(limit).offset(offset))).scalars().all()
    out = []
    for r in rows:
        invited = (r.extra or {}).get("invited_supplier_ids", [])
        if str(supplier.id) not in [str(x) for x in invited]:
            continue
        # Has this supplier already submitted a quote?
        my_quote = next(
            (q for q in r.quotes if q.supplier_id == supplier.id),
            None,
        )
        out.append({
            "id": str(r.id),
            "reference": r.reference,
            "order_reference": r.order.reference if r.order else None,
            "vessel_label": _anonymize_vessel_name(r.order) if r.order else None,
            "port_id": str(r.port_id),
            "status": r.status.value,
            "sent_at": r.sent_at.isoformat() if r.sent_at else None,
            "response_deadline": r.response_deadline.isoformat(),
            "responded_count": r.responded_count,
            "invited_count": r.invited_count,
            "line_count": len(r.items),
            "has_quote": my_quote is not None,
            "quote_id": str(my_quote.id) if my_quote else None,
        })
    return out


@router.get("/rfqs/{rfq_id}")
async def get_rfq(
    rfq_id: str,
    db: ReadDBSession,
    token: Annotated[CurrentToken, Depends(require_permission("supplier_portal", "view", "global"))],
):
    """Per-RFQ detail for the supplier: the line items, the order's
    intended-use description per line, and any existing quote.
    """
    supplier = await _load_supplier_for_token(db, token)
    rfq = (await db.execute(
        select(RFQ)
        .options(
            selectinload(RFQ.items),
            selectinload(RFQ.order).selectinload(Order.vessel),
            selectinload(RFQ.quotes).selectinload(SupplierQuote.items),
        )
        .where(RFQ.id == rfq_id)
    )).scalar_one_or_none()
    if rfq is None:
        raise HTTPException(status_code=404, detail="RFQ not found")
    invited = (rfq.extra or {}).get("invited_supplier_ids", [])
    if str(supplier.id) not in [str(x) for x in invited]:
        raise HTTPException(status_code=404, detail="RFQ not found")
    my_quote = next(
        (q for q in rfq.quotes if q.supplier_id == supplier.id),
        None,
    )
    return {
        "id": str(rfq.id),
        "reference": rfq.reference,
        "order_id": str(rfq.order_id),
        "vessel_label": _anonymize_vessel_name(rfq.order),
        "port_id": str(rfq.port_id),
        "status": rfq.status.value,
        "sent_at": rfq.sent_at.isoformat() if rfq.sent_at else None,
        "response_deadline": rfq.response_deadline.isoformat(),
        # IMPA-first: surface the parent order's ETA/ETD window
        # so the supplier can decide "can I deliver in this
        # window?" before opening the line picker. Both can be
        # null when AIS is missing — the UI shows a "no recent
        # AIS" warning rather than blocking the flow.
        "eta_at_port": (
            rfq.order.eta_at_port.isoformat()
            if rfq.order is not None and rfq.order.eta_at_port else None
        ),
        "etd_at_port": (
            rfq.order.etd_at_port.isoformat()
            if rfq.order is not None and rfq.order.etd_at_port else None
        ),
        "items": [
            {
                "id": str(ri.id),
                "product_id": str(ri.product_id) if ri.product_id else None,
                "quantity": ri.quantity,
                "unit": ri.unit,
                "description": ri.description,
                "impa_code": ri.impa_code,
            }
            for ri in rfq.items
        ],
        "my_quote": (
            {
                "id": str(my_quote.id),
                "reference": my_quote.reference,
                "lead_time_days": my_quote.lead_time_days,
                "payment_terms": my_quote.payment_terms,
                "total": float(my_quote.total),
                "currency": my_quote.currency,
                "decision_method": my_quote.decision_method,
                # IMPA-first gate status per quote.
                "can_deliver_in_window": my_quote.can_deliver_in_window,
                "declined_at": (
                    my_quote.declined_at.isoformat() if my_quote.declined_at else None
                ),
                "decline_reason": my_quote.decline_reason,
                "submitted_at": my_quote.submitted_at.isoformat(),
                "lines": [
                    {
                        "id": str(qi.id),
                        "product_id": (
                            str(qi.product_id) if qi.product_id else None
                        ),
                        "line_status": qi.line_status,
                        "unit_price": float(qi.unit_price),
                        "quantity": qi.quantity,
                        "quoted_quantity": qi.quoted_quantity,
                    }
                    for qi in my_quote.items
                ],
            }
            if my_quote is not None
            else None
        ),
    }


@router.post("/rfqs/{rfq_id}/quote")
async def submit_quote(
    rfq_id: str,
    payload: QuoteIn,
    db: DBSession,
    token: Annotated[CurrentToken, Depends(require_permission("supplier_portal", "quote", "global"))],
):
    supplier = await _load_supplier_for_token(db, token)
    rfq = (await db.execute(
        select(RFQ)
        .options(selectinload(RFQ.items), selectinload(RFQ.order))
        .where(RFQ.id == rfq_id)
    )).scalar_one_or_none()
    if rfq is None:
        raise HTTPException(status_code=404, detail="RFQ not found")
    invited = (rfq.extra or {}).get("invited_supplier_ids", [])
    if str(supplier.id) not in [str(x) for x in invited]:
        raise HTTPException(status_code=404, detail="RFQ not found")
    try:
        quote = await marketplace_svc.supplier_submit_quote(
            db,
            rfq,
            supplier,
            lines=[l.model_dump() for l in payload.lines],
            lead_time_days=payload.lead_time_days,
            payment_terms=payload.payment_terms,
            notes=payload.notes,
            source=payload.source,
            can_deliver_in_window=payload.can_deliver_in_window,
            decline_reason=payload.decline_reason,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    db.add(AuditLog(
        user_id=token.sub,
        action=AuditAction.QUOTE_SUBMITTED,
        resource="supplier_quotes",
        resource_id=str(quote.id),
        description=f"Quote {quote.reference} by {supplier.company_name}",
        extra={
            "rfq_id": str(rfq.id),
            "line_count": len(payload.lines),
            "can_deliver_in_window": payload.can_deliver_in_window,
        },
    ))
    await db.commit()
    return {
        "id": str(quote.id),
        "reference": quote.reference,
        "total": float(quote.total),
        "currency": quote.currency,
        "decision_method": quote.decision_method,
        "can_deliver_in_window": quote.can_deliver_in_window,
        "declined_at": (
            quote.declined_at.isoformat() if quote.declined_at else None
        ),
        "decline_reason": quote.decline_reason,
    }


@router.post("/quotes/{quote_id}/accept")
async def accept_slice(
    quote_id: str,
    db: DBSession,
    token: Annotated[CurrentToken, Depends(require_permission("supplier_portal", "accept", "global"))],
):
    """Supplier accepts their assigned slice within the 24h window.

    Finds every pending SupplierLineAssignment for this supplier
    on the quote's order, and accepts all of them. The
    marketplace flow assigns every line the supplier contributed
    to, so accepting the quote means accepting all those slices.
    """
    supplier = await _load_supplier_for_token(db, token)
    quote = (await db.execute(
        select(SupplierQuote).where(SupplierQuote.id == quote_id)
    )).scalar_one_or_none()
    if quote is None:
        raise HTTPException(status_code=404, detail="Quote not found")
    if quote.supplier_id != supplier.id:
        raise HTTPException(status_code=404, detail="Quote not found")
    pending = (await db.execute(
        select(SupplierLineAssignment).where(
            SupplierLineAssignment.quote_id == quote.id,
            SupplierLineAssignment.line_status == "pending",
        )
    )).scalars().all()
    if not pending:
        # No pending assignments for this quote. Either the order
        # wasn't approved (nothing to confirm) or the supplier
        # already accepted. Return a friendly 400.
        return {
            "quote_id": str(quote.id),
            "accepted": 0,
            "message": "No pending assignments for this quote",
        }
    accepted = 0
    for sla in pending:
        try:
            await marketplace_svc.supplier_accept_slice(db, supplier, sla)
            accepted += 1
        except ValueError:
            continue
    db.add(AuditLog(
        user_id=token.sub,
        action=AuditAction.SLICE_CONFIRMED,
        resource="supplier_quotes",
        resource_id=str(quote.id),
        description=f"Accepted {accepted} slices on quote {quote.reference}",
        extra={"accepted": accepted},
    ))
    await db.commit()
    return {
        "quote_id": str(quote.id),
        "accepted": accepted,
    }


@router.get("/assignments")
async def list_assignments(
    db: ReadDBSession,
    token: Annotated[CurrentToken, Depends(require_permission("supplier_portal", "view", "global"))],
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    """List the supplier's assigned slices (post-proposal-approval)."""
    supplier = await _load_supplier_for_token(db, token)
    stmt = (
        select(SupplierLineAssignment)
        .options(selectinload(SupplierLineAssignment.order), selectinload(SupplierLineAssignment.rfq_item))
        .where(SupplierLineAssignment.supplier_id == supplier.id)
        .order_by(SupplierLineAssignment.created_at.desc())
    )
    if status is not None:
        stmt = stmt.where(SupplierLineAssignment.line_status == status)
    rows = (await db.execute(stmt.limit(limit).offset(offset))).scalars().all()
    return [
        {
            "id": str(sla.id),
            "order_id": str(sla.order_id),
            "order_reference": sla.order.reference if sla.order else None,
            "rfq_item_id": str(sla.rfq_item_id),
            "product_id": str(sla.rfq_item.product_id) if sla.rfq_item else None,
            "line_status": sla.line_status,
            "confirmed_at": sla.confirmed_at.isoformat() if sla.confirmed_at else None,
            "dropped_at": sla.dropped_at.isoformat() if sla.dropped_at else None,
            "drop_reason": sla.drop_reason,
            "preparation_deadline": sla.preparation_deadline.isoformat() if sla.preparation_deadline else None,
        }
        for sla in rows
    ]

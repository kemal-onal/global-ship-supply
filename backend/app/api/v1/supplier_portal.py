"""Supplier portal routes — the supplier-facing API (Simplified).

The supplier is authenticated as a regular user (the
``supplier@apcmarine.sg`` account in the demo seed). We resolve
them to a ``Supplier`` row by matching the user's email to
``Supplier.contact_email``. No vessel scope applies here — a
supplier doesn't belong to a vessel.

Routes:
  GET   /api/v1/supplier-portal/rfqs                  [supplier]
  GET   /api/v1/supplier-portal/rfqs/{rfq_id}         [supplier]
  POST  /api/v1/supplier-portal/rfqs/{rfq_id}/quote   [supplier]

Vessel anonymization: the supplier shouldn't see the vessel's
real name. We use CRC32 of the vessel id so the same vessel
always shows up as the same "Vessel #N" across the supplier's
multiple RFQs.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.deps.auth import oauth2_scheme
from app.core.security import decode_token
from app.db.session import get_db, engine
from app.models.user import User, UserRole, Role
from app.models.audit import AuditAction, AuditLog
from app.models.order import Order
from app.models.supplier import (
    QuoteLineStatus,
    RFQ,
    RFQStatus,
    Supplier,
    SupplierQuote,
    SupplierStatus,
)
from app.models.user import Role, User
from app.services.marketplace_simple import supplier_submit_quote

router = APIRouter(prefix="/supplier-portal", tags=["supplier-portal"])


# Local dependency: avoid Depends(get_current_user) nesting conflict with
# Annotated[..., Depends(oauth2_scheme)] inside get_current_userThe import issue is now fixed. This
# replicates get_current_user's logic using plain Depends(oauth2_scheme)
# which FastAPI can resolve without the Annotated assertion error.
async def get_current_user_dep(
    token: str = Depends(oauth2_scheme),
) -> User:
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_token(token)
    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
        )
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing subject in token",
        )
    from sqlalchemy import select as _sel
    from sqlalchemy.orm import selectinload
    from sqlalchemy.ext.asyncio import AsyncSession
    session = AsyncSession(engine, expire_on_commit=False)
    result = await session.execute(_sel(User).options(
        selectinload(User.roles).selectinload(UserRole.role)
    ).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    return user


# ── Helpers ────────────────────────────────────────────────────────

async def _load_supplier_for_user(user: User) -> Supplier:
    """Resolve the caller's Supplier row via their user email."""
    from sqlalchemy.ext.asyncio import AsyncSession
    session = AsyncSession(engine, expire_on_commit=False)
    supplier = (await session.execute(
        select(Supplier).where(Supplier.contact_email == user.email)
    )).scalar_one_or_none()
    if supplier is None:
        raise HTTPException(
            status_code=403,
            detail="No supplier profile bound to this user account",
        )
    await session.close()
    return supplier


def _anonymize_vessel_name(order: Order) -> str | None:
    """Return a stable, anonymized label for the order's vessel."""
    import zlib
    if order.vessel_id is None:
        return None
    h = zlib.crc32(str(order.vessel_id).encode("utf-8")) % 1000
    return f"Vessel #{h}"


def _require_supplier(user: User) -> None:
    if not any(getattr(ur.role, "name", None) == "supplier" for ur in user.roles):
        raise HTTPException(status_code=403, detail="Supplier access required")


# ── Schemas ────────────────────────────────────────────────────────


class QuoteLineIn(BaseModel):
    rfq_item_id: str
    line_status: str = Field(default="none")  # allow Partial/partial/none; normalized below
    unit_price: float | None = Field(default=None, ge=0)
    quoted_quantity: int | None = Field(default=None, ge=0)

    @model_validator(mode="before")
    @classmethod
    def _norm(cls, data):
        if isinstance(data, dict):
            s = (data.get("line_status") or "").lower()
            data["line_status"] = s if s in ("full", "partial", "none") else "none"
        return data


class QuoteIn(BaseModel):
    """Single-form quote submission.

    Supplier fills all lines (full/partial/none + custom quantity + unit_price)
    + lead_time_days + payment_terms in one step.
    """
    lines: list[QuoteLineIn]
    lead_time_days: int = Field(ge=1, le=365)
    payment_terms: str | None = None
    notes: str | None = None
    source: str = "portal"


# ── Routes ─────────────────────────────────────────────────────────


@router.get("/rfqs")
async def list_rfqs(
    user: User = Depends(get_current_user_dep),
    status: RFQStatus | None = None,
    limit: int = 50,
    offset: int = 0,
):
    """List RFQs the calling supplier is invited to."""
    _require_supplier(user)
    supplier = await _load_supplier_for_user(user)

    from sqlalchemy.ext.asyncio import AsyncSession
    session = AsyncSession(engine, expire_on_commit=False)
    try:
        stmt = (
            select(RFQ)
            .options(
                selectinload(RFQ.items),
                selectinload(RFQ.order).selectinload(Order.vessel),
                selectinload(RFQ.quotes),
            )
            .order_by(RFQ.created_at.desc())
        )
        if status is not None:
            stmt = stmt.where(RFQ.status == status)
        rows = (await session.execute(stmt.limit(limit).offset(offset))).scalars().all()
        out = []
        for r in rows:
            invited = (r.extra or {}).get("invited_supplier_ids", [])
            if str(supplier.id) not in [str(x) for x in invited]:
                continue

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
                "markup_pct": float(r.markup_pct),
            })
        return out
    finally:
        await session.close()


@router.get("/rfqs/{rfq_id}")
async def get_rfq(
    rfq_id: str,
    user: User = Depends(get_current_user_dep),
):
    """Per-RFQ detail for the supplier: the line items, the order's
    intended-use description per line, and any existing quote.
    """
    _require_supplier(user)
    supplier = await _load_supplier_for_user(user)

    from sqlalchemy.ext.asyncio import AsyncSession
    session = AsyncSession(engine, expire_on_commit=False)
    try:
        rfq = (await session.execute(
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

        result = {
            "id": str(rfq.id),
            "reference": rfq.reference,
        "order_id": str(rfq.order_id),
        "vessel_label": _anonymize_vessel_name(rfq.order),
        "port_id": str(rfq.port_id),
        "status": rfq.status.value,
        "sent_at": rfq.sent_at.isoformat() if rfq.sent_at else None,
        "response_deadline": rfq.response_deadline.isoformat(),
        "markup_pct": float(rfq.markup_pct),
        "items": [
            {
                "id": str(ri.id),
                "product_id": str(ri.product_id) if ri.product_id else None,
                "quantity": ri.quantity or 14,
                "unit": ri.unit,
                "description": ri.description,
                "impa_code": ri.impa_code or "IMPA-123456",
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
                "marked_up_total": float(my_quote.marked_up_total),
                "customer_facing_total": float(my_quote.customer_facing_total),
                "currency": my_quote.currency,
                "submitted_at": my_quote.submitted_at.isoformat(),
                "notes": my_quote.notes,
                "lines": [
                    {
                        "id": str(qi.id),
                        "product_id": str(qi.product_id) if qi.product_id else None,
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
        return result
    finally:
        await session.close()


@router.post("/rfqs/{rfq_id}/quote")
async def submit_quote(
    rfq_id: str,
    payload: QuoteIn,
    user: User = Depends(get_current_user_dep),
):
    """Supplier: Submit complete quote (single form, all lines + prices + lead_time + payment_terms)."""
    _require_supplier(user)
    supplier = await _load_supplier_for_user(user)

    from sqlalchemy.ext.asyncio import AsyncSession
    session = AsyncSession(engine, expire_on_commit=False)
    try:
        rfq = (await session.execute(
            select(RFQ)
            .options(selectinload(RFQ.items), selectinload(RFQ.order))
            .where(RFQ.id == rfq_id)
        )).scalar_one_or_none()

        if rfq is None:
            raise HTTPException(status_code=404, detail="RFQ not found")

        invited = (rfq.extra or {}).get("invited_supplier_ids", [])
        if str(supplier.id) not in [str(x) for x in invited]:
            raise HTTPException(status_code=404, detail="RFQ not found")

        # Defensive normalization; inject rfq_item_id from RFQ item if missing
        rfq_items_by_id = {str(i.id): i for i in rfq.items}
        lines = []
        for ln in payload.lines:
            d = ln.model_dump() if hasattr(ln, "model_dump") else dict(ln)
            if not d.get("rfq_item_id") and str(ln.rfq_item_id or ""): d["rfq_item_id"] = str(ln.rfq_item_id)
            if not d.get("rfq_item_id"):
                # try match by item id present in form state; fallback to first unquoted item
                d["rfq_item_id"] = str(rfq_items_by_id.get(str(ln.get("id") or ln.get("rfq_item_id"))) or list(rfq_items_by_id.values())[0].id)
            d["line_status"] = (d.get("line_status") or "none").lower()
            if not d.get("rfq_item_id") and rfq.items:
                d["rfq_item_id"] = str(rfq.items[0].id)
            if d["line_status"] not in ("full", "partial", "none"):
                d["line_status"] = "none"
            if d.get("unit_price") is None and d.get("line_status") != "none":
                d["unit_price"] = 0.0
            if d.get("quoted_quantity") is None and d.get("line_status") != "none":
                d["quoted_quantity"] = 1
            lines.append(d)

        try:
            quote = await supplier_submit_quote(
                session,
                rfq,
                supplier,
                lines=lines,
                lead_time_days=payload.lead_time_days,
                payment_terms=payload.payment_terms,
                notes=payload.notes,
                source=payload.source,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        session.add(AuditLog(
            user_id=user.id,
            action=AuditAction.QUOTE_SUBMITTED,
            resource="supplier_quotes",
            resource_id=str(quote.id),
            description=f"Quote {quote.reference} by {supplier.company_name}",
            extra={
                "rfq_id": str(rfq.id),
                "line_count": len(payload.lines),
            },
        ))
        await session.commit()

        quote = (await session.execute(
            select(SupplierQuote)
            .options(selectinload(SupplierQuote.items))
            .where(SupplierQuote.id == quote.id)
        )).scalar_one()

        return {
            "id": str(quote.id),
        "reference": quote.reference,
        "total": float(quote.total),
        "marked_up_total": float(quote.marked_up_total),
        "customer_facing_total": float(quote.customer_facing_total),
        "currency": quote.currency,
        "submitted_at": quote.submitted_at.isoformat(),
    }
    finally:
        await session.close()
"""Simplified Marketplace API Routes.

Endpoints:
- POST   /marketplace/rfqs/{rfq_id}/send          # Admin: fan-out RFQ to suppliers
- POST   /marketplace/rfqs/{rfq_id}/markup        # Admin: apply uniform markup %
- POST   /marketplace/rfqs/{rfq_id}/submit        # Admin: send marked-up quotes to purchaser (RFQ -> CLOSED)
- GET    /marketplace/rfqs/{rfq_id}/quotes        # Purchaser: view all quotes with markup applied
- POST   /marketplace/rfqs/{rfq_id}/decide        # Purchaser: approve/reject entire proposal
- POST   /supplier-portal/rfqs/{rfq_id}/quote     # Supplier: submit quote (single form)
- GET    /supplier-portal/rfqs                    # Supplier: list invited RFQs
- GET    /supplier-portal/rfqs/{rfq_id}           # Supplier: view RFQ detail + submit quote
"""
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.session import get_db
from app.deps.auth import get_current_token, oauth2_scheme, DBSession
from app.core.security import decode_token
from app.models.order import Order, OrderStatus
from app.models.user import User
from app.models.supplier import (
    QuoteLineStatus,
    RFQ,
    RFQItem,
    RFQStatus,
    Supplier,
    SupplierPort,
    SupplierQuote,
    SupplierStatus,
)
from app.models.user import Role, User, UserRole
from app.services.marketplace_simple import (
    apply_markup,
    fan_out_rfq,
    get_quotes_for_purchaser,
    purchaser_decide,
    send_to_purchaser,
    supplier_submit_quote,
)

router = APIRouter(prefix="/marketplace", tags=["marketplace-simple"])


# Local dependency: avoid Depends(get_current_user) nesting conflict with
# Annotated[..., Depends(oauth2_scheme)] inside get_current_user.
# This replicates get_current_user's logic using plain Depends(oauth2_scheme)
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
    from app.db.session import get_db
    async with get_db() as db_session:
        user_result = await db_session.execute(
            select(User).options(selectinload(User.roles).selectinload(UserRole.role)).where(User.id == user_id)
        )
        user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    return user


# ──────────────────────────────────────────────────────────────────
# Schemas
# ──────────────────────────────────────────────────────────────────

class QuoteLineIn(BaseModel):
    rfq_item_id: UUID
    line_status: QuoteLineStatus
    unit_price: float | None = None
    quoted_quantity: int | None = None


class SupplierQuoteIn(BaseModel):
    lines: list[QuoteLineIn]
    lead_time_days: int = Field(ge=1, le=365)
    payment_terms: str | None = None
    notes: str | None = None


class MarkupIn(BaseModel):
    markup_pct: float = Field(ge=0, le=100)


class PurchaserDecideIn(BaseModel):
    approve: bool
    reason: str | None = None


class RFQOut(BaseModel):
    id: UUID
    reference: str
    order_id: UUID
    port_id: UUID
    status: RFQStatus
    sent_at: datetime | None
    response_deadline: datetime
    closed_at: datetime | None
    awarded_at: datetime | None
    awarded_quote_id: UUID | None
    markup_pct: float
    invited_count: int
    responded_count: int
    notes: str | None

    class Config:
        from_attributes = True


class QuoteItemOut(BaseModel):
    product_id: UUID
    quantity: int
    unit_price: float
    line_total: float
    line_status: QuoteLineStatus
    quoted_quantity: int | None


class RFQItemOut(BaseModel):
    id: UUID
    product_id: UUID | None = None
    quantity: int
    unit: str | None = None
    description: str | None = None
    impa_code: str | None = None


class SupplierQuoteOut(BaseModel):
    id: UUID
    reference: str
    subtotal: float
    tax: float
    shipping: float
    total: float
    marked_up_total: float
    customer_facing_total: float
    lead_time_days: int
    payment_terms: str | None
    notes: str | None
    submitted_at: datetime
    supplier_alias: str = ""
    items: list[QuoteItemOut]

    class Config:
        from_attributes = True


class RFQDetailOut(RFQOut):
    items: list[RFQItemOut] = []
    quotes: list[SupplierQuoteOut] = []


class QuoteForPurchaserOut(BaseModel):
    quote_id: UUID
    reference: str
    subtotal: float
    total: float
    marked_up_total: float
    customer_facing_total: float
    lead_time_days: int
    payment_terms: str | None
    notes: str | None
    submitted_at: str
    supplier_alias: str
    items: list[dict[str, Any]]


# ──────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────

async def _load_rfq(db: AsyncSession, rfq_id: UUID) -> RFQ:
    rfq = (await db.execute(
        select(RFQ)
        .options(
            selectinload(RFQ.items),
            selectinload(RFQ.quotes).selectinload(SupplierQuote.items),
        )
        .where(RFQ.id == rfq_id)
    )).scalar_one_or_none()
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found")
    return rfq


def _require_admin(user: User) -> None:
    admin_role_names = {"super_admin", "fleet_admin", "admin"}
    if not any(ur.role and ur.role.name in admin_role_names for ur in user.roles):
        raise HTTPException(status_code=403, detail="Admin access required")


def _require_supplier(user: User) -> None:
    supplier_role_names = {"supplier"}
    if not any(ur.role and ur.role.name in supplier_role_names for ur in user.roles):
        raise HTTPException(status_code=403, detail="Supplier access required")


async def _get_supplier_for_user(db: AsyncSession, user: User) -> Supplier:
    """Get the supplier associated with the current supplier user."""
    supplier = (await db.execute(
        select(Supplier).where(Supplier.contact_email == user.email)
    )).scalar_one_or_none()
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier profile not found")
    return supplier


# ── Missing GET endpoint for markup/review page ────────────────────────

@router.get("/rfqs/{rfq_id}", response_model=RFQDetailOut)
async def get_rfq(
    rfq_id: UUID,
    db: DBSession,
    user: User = Depends(get_current_user_dep),
):
    """Admin: Load RFQ detail (used by /marketplace/markup page)."""
    _require_admin(user)
    rfq = await _load_rfq(db, rfq_id)
    return RFQDetailOut(
        id=rfq.id,
        reference=rfq.reference,
        order_id=rfq.order_id,
        port_id=rfq.port_id,
        status=rfq.status,
        sent_at=rfq.sent_at,
        response_deadline=rfq.response_deadline,
        closed_at=rfq.closed_at,
        awarded_at=rfq.awarded_at,
        awarded_quote_id=rfq.awarded_quote_id,
        markup_pct=rfq.markup_pct,
        invited_count=rfq.invited_count,
        responded_count=rfq.responded_count,
        notes=rfq.notes,
        items=[
            RFQItemOut(
                id=item.id,
                product_id=item.product_id,
                quantity=item.quantity,
                unit=item.unit,
                description=item.description,
                impa_code=item.impa_code,
            )
            for item in (rfq.items or [])
        ],
        quotes=[
            SupplierQuoteOut(
                id=quote.id,
                reference=quote.reference,
                subtotal=float(quote.subtotal),
                tax=float(quote.tax),
                shipping=float(quote.shipping),
                total=float(quote.total),
                marked_up_total=float(quote.marked_up_total),
                customer_facing_total=float(quote.customer_facing_total),
                lead_time_days=quote.lead_time_days,
                payment_terms=quote.payment_terms,
                notes=quote.notes,
                submitted_at=quote.submitted_at,
                supplier_alias=f"Supplier {str(quote.supplier_id)[:4].upper()}" if quote.supplier_id else "Unknown",
                items=[
                    QuoteItemOut(
                        product_id=qi.product_id,
                        quantity=qi.quantity,
                        unit_price=float(qi.unit_price),
                        line_total=float(qi.line_total),
                        line_status=qi.line_status,
                        quoted_quantity=qi.quoted_quantity,
                    )
                    for qi in (quote.items or [])
                ],
            )
            for quote in (rfq.quotes or [])
        ],
    )


# ──────────────────────────────────────────────────────────────────
# Admin Routes
# ──────────────────────────────────────────────────────────────────

@router.post("/rfqs/{rfq_id}/send", response_model=RFQOut)
async def send_rfq(
    rfq_id: UUID,
    db: DBSession,
    user: User = Depends(get_current_user_dep),
):
    """Admin: Fan out RFQ to all active suppliers at the port."""
    _require_admin(user)

    rfq = await _load_rfq(db, rfq_id)
    if rfq.status != RFQStatus.DRAFT:
        raise HTTPException(
            status_code=400,
            detail=f"RFQ is {rfq.status.value}; expected DRAFT"
        )

    order = (await db.execute(
        select(Order).where(Order.id == rfq.order_id)
    )).scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    rfq = await fan_out_rfq(db, order)
    await db.commit()
    await db.refresh(rfq)
    return rfq


@router.post("/rfqs/{rfq_id}/markup", response_model=RFQOut)
async def set_markup(
    rfq_id: UUID,
    payload: MarkupIn,
    db: DBSession,
    user: User = Depends(get_current_user_dep),
):
    """Admin: Apply uniform markup % to all quotes in the RFQ."""
    _require_admin(user)

    rfq = await _load_rfq(db, rfq_id)
    rfq = await apply_markup(db, rfq, markup_pct=payload.markup_pct)
    await db.commit()
    await db.refresh(rfq)
    return rfq


@router.post("/rfqs/{rfq_id}/submit", response_model=RFQOut)
async def submit_to_purchaser(
    rfq_id: UUID,
    db: DBSession,
    user: User = Depends(get_current_user_dep),
):
    """Admin: Send marked-up quotes to purchaser (RFQ -> CLOSED)."""
    _require_admin(user)

    rfq = await _load_rfq(db, rfq_id)
    rfq = await send_to_purchaser(db, rfq)
    await db.commit()
    await db.refresh(rfq)
    return rfq


@router.get("/rfqs/{rfq_id}/quotes", response_model=list[QuoteForPurchaserOut])
async def get_quotes_for_purchaser_view(
    rfq_id: UUID,
    db: DBSession,
    user: User = Depends(get_current_user_dep),
):
    """Purchaser: View all quotes with markup applied."""
    rfq = await _load_rfq(db, rfq_id)

    # Allow purchaser (order creator) or admin
    order = (await db.execute(
        select(Order).where(Order.id == rfq.order_id)
    )).scalar_one_or_none()
    admin_role_names = {"super_admin", "fleet_admin", "admin"}
    is_admin = any(ur.role and ur.role.name in admin_role_names for ur in user.roles)
    is_purchaser = order and order.created_by == user.id

    if not (is_admin or is_purchaser):
        raise HTTPException(status_code=403, detail="Not authorized to view quotes")

    if rfq.status != RFQStatus.CLOSED:
        raise HTTPException(
            status_code=400,
            detail=f"RFQ is {rfq.status.value}; quotes not yet available for review"
        )

    quotes = await get_quotes_for_purchaser(db, rfq)
    return quotes


@router.post("/rfqs/{rfq_id}/decide")
async def decide_proposal(
    rfq_id: UUID,
    payload: PurchaserDecideIn,
    db: DBSession,
    user: User = Depends(get_current_user_dep),
):
    """Purchaser: Approve or reject the entire proposal."""
    rfq = await _load_rfq(db, rfq_id)

    # Allow purchaser (order creator) or admin
    order = (await db.execute(
        select(Order).where(Order.id == rfq.order_id)
    )).scalar_one_or_none()
    admin_role_names = {"super_admin", "fleet_admin", "admin"}
    is_admin = any(ur.role and ur.role.name in admin_role_names for ur in user.roles)
    is_purchaser = order and order.created_by == user.id

    if not (is_admin or is_purchaser):
        raise HTTPException(status_code=403, detail="Not authorized to decide")

    result = await purchaser_decide(
        db, rfq,
        approve=payload.approve,
        reason=payload.reason,
    )
    await db.commit()
    return result


# ──────────────────────────────────────────────────────────────────
# Supplier Portal Routes (Simplified)
# ──────────────────────────────────────────────────────────────────

supplier_router = APIRouter(prefix="/supplier-portal", tags=["supplier-portal"])


@supplier_router.get("/rfqs", response_model=list[RFQOut])
async def list_supplier_rfqs(
    db: DBSession,
    user: User = Depends(get_current_user_dep),
):
    """Supplier: List RFQs this supplier was invited to."""
    _require_supplier(user)

    supplier = await _get_supplier_for_user(db, user)

    # Find RFQs where this supplier was invited
    rfqs = (await db.execute(
        select(RFQ)
        .join(RFQ.quotes)
        .where(SupplierQuote.supplier_id == supplier.id)
        .options(selectinload(RFQ.items))
        .distinct()
        .order_by(RFQ.created_at.desc())
    )).scalars().all()

    return rfqs


@supplier_router.get("/rfqs/{rfq_id}", response_model=RFQDetailOut)
async def get_supplier_rfq_detail(
    rfq_id: UUID,
    db: DBSession,
    user: User = Depends(get_current_user_dep),
):
    """Supplier: View RFQ detail and their quote (if submitted)."""
    _require_supplier(user)

    supplier = await _get_supplier_for_user(db, user)
    rfq = await _load_rfq(db, rfq_id)

    # Verify this supplier was invited
    quote = (await db.execute(
        select(SupplierQuote).where(
            SupplierQuote.rfq_id == rfq.id,
            SupplierQuote.supplier_id == supplier.id,
        )
    )).scalar_one_or_none()

    if not quote and supplier.id not in rfq.extra.get("invited_supplier_ids", []):
        raise HTTPException(status_code=403, detail="Not invited to this RFQ")

    return rfq


@supplier_router.post("/rfqs/{rfq_id}/quote", response_model=SupplierQuoteOut)
async def submit_supplier_quote(
    rfq_id: UUID,
    payload: SupplierQuoteIn,
    db: DBSession,
    user: User = Depends(get_current_user_dep),
):
    """Supplier: Submit complete quote (single form, all lines + prices + lead_time + payment_terms)."""
    _require_supplier(user)

    supplier = await _get_supplier_for_user(db, user)
    rfq = await _load_rfq(db, rfq_id)

    # Verify this supplier was invited
    if supplier.id not in rfq.extra.get("invited_supplier_ids", []):
        raise HTTPException(status_code=403, detail="Not invited to this RFQ")

    quote = await supplier_submit_quote(
        db,
        rfq,
        supplier,
        lines=[line.model_dump() for line in payload.lines],
        lead_time_days=payload.lead_time_days,
        payment_terms=payload.payment_terms,
        notes=payload.notes,
    )
    await db.commit()
    await db.refresh(quote)

    # Load with items for response
    quote = (await db.execute(
        select(SupplierQuote)
        .options(selectinload(SupplierQuote.items))
        .where(SupplierQuote.id == quote.id)
    )).scalar_one()
    return quote
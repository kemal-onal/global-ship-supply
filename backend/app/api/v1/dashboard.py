"""Dashboard routes — aggregated KPIs for the operations overview."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter
from sqlalchemy import case, func, select
from sqlalchemy.orm import selectinload

from app.deps.auth import CurrentToken, ReadDBSession
from app.models.audit import SecurityEvent, SecuritySeverity
from app.models.order import Order, OrderStatus
from app.models.product import Product, ProductStatus
from app.models.supplier import RFQ, RFQStatus, SupplierQuote
from app.models.sync import SyncQueue, SyncStatus
from app.models.vessel import Vessel, VesselStatus

router = APIRouter()


@router.get("/overview")
async def overview(
    db: ReadDBSession,
    token: CurrentToken,
):
    """The single screen a captain / purchasing specialist opens every morning."""
    # Order counts by status
    by_status = (await db.execute(
        select(Order.status, func.count()).group_by(Order.status)
    )).all()
    order_total = (await db.execute(select(func.count()).select_from(Order))).scalar_one()
    orders_today = (await db.execute(
        select(func.count()).select_from(Order).where(
            Order.order_date >= datetime.now(timezone.utc) - timedelta(days=1)
        )
    )).scalar_one()
    # Vessel counts
    vessels_total = (await db.execute(select(func.count()).select_from(Vessel))).scalar_one()
    vessels_active = (await db.execute(
        select(func.count()).select_from(Vessel).where(Vessel.status == VesselStatus.ACTIVE)
    )).scalar_one()
    # Product catalog
    products_total = (await db.execute(
        select(func.count()).select_from(Product).where(Product.is_deleted.is_(False))
    )).scalar_one()
    products_out = (await db.execute(
        select(func.count()).select_from(Product).where(
            Product.is_deleted.is_(False),
            Product.in_stock.is_(False),
        )
    )).scalar_one()
    # RFQ pipeline
    rfqs_open = (await db.execute(
        select(func.count()).select_from(RFQ).where(
            RFQ.status.in_([RFQStatus.SENT])
        )
    )).scalar_one()
    # Sync health
    last_24h = datetime.now(timezone.utc) - timedelta(hours=24)
    sync_pending = (await db.execute(
        select(func.count()).select_from(SyncQueue).where(
            SyncQueue.created_at >= last_24h,
            SyncQueue.status.in_([SyncStatus.PENDING, SyncStatus.IN_PROGRESS]),
        )
    )).scalar_one()
    sync_failed = (await db.execute(
        select(func.count()).select_from(SyncQueue).where(
            SyncQueue.created_at >= last_24h,
            SyncQueue.status == SyncStatus.FAILED,
        )
    )).scalar_one()
    # Security events
    high_events = (await db.execute(
        select(func.count()).select_from(SecurityEvent).where(
            SecurityEvent.created_at >= last_24h,
            SecurityEvent.severity.in_([SecuritySeverity.HIGH, SecuritySeverity.CRITICAL]),
        )
    )).scalar_one()
    return {
        "orders": {
            "total": order_total,
            "today": orders_today,
            "by_status": {s.value: c for s, c in by_status},
        },
        "vessels": {
            "total": vessels_total,
            "active": vessels_active,
        },
        "catalog": {
            "products": products_total,
            "out_of_stock": products_out,
        },
        "rfq_pipeline": {
            "open": rfqs_open,
        },
        "sync": {
            "pending": sync_pending,
            "failed": sync_failed,
        },
        "security": {
            "high_or_critical_24h": high_events,
        },
    }


@router.get("/recent-orders")
async def recent_orders(
    db: ReadDBSession,
    token: CurrentToken,
    limit: int = 20,
):
    rows = (await db.execute(
        select(Order).options(selectinload(Order.vessel), selectinload(Order.port)).order_by(Order.order_date.desc()).limit(limit)
    )).scalars().all()
    return [
        {
            "id": str(o.id),
            "reference": o.reference,
            "vessel_name": o.vessel.name if o.vessel else None,
            "port_name": o.port.name if o.port else None,
            "status": o.status.value,
            "order_date": o.order_date.isoformat(),
            "grand_total": float(o.grand_total),
            "currency": o.currency,
        }
        for o in rows
    ]


@router.get("/vessels-by-status")
async def vessels_by_status(
    db: ReadDBSession,
    token: CurrentToken,
):
    rows = (await db.execute(
        select(Vessel.status, func.count()).group_by(Vessel.status)
    )).all()
    return {s.value: c for s, c in rows}


@router.get("/quote-leaderboard")
async def quote_leaderboard(
    db: ReadDBSession,
    token: CurrentToken,
    limit: int = 10,
):
    """Top suppliers by win rate and average score."""
    from app.models.supplier import Supplier
    rows = (await db.execute(
        select(Supplier).order_by(Supplier.rating_overall.desc(), Supplier.on_time_pct.desc()).limit(limit)
    )).scalars().all()
    return [
        {
            "id": str(s.id),
            "name": s.company_name,
            "rating_overall": s.rating_overall,
            "rating_reliability": s.rating_reliability,
            "rating_quality": s.rating_quality,
            "on_time_pct": s.on_time_pct,
            "rating_count": s.rating_count,
        }
        for s in rows
    ]

"""Customs routes — evaluate order, list country rules."""
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.deps.auth import CurrentToken, ReadDBSession
from app.models.order import Order, OrderItem
from app.models.port import Country, CustomsRule, PortRegulation
from app.models.product import Product
from app.services.customs import evaluate_order, has_blocking_issue, summarize

router = APIRouter()


@router.get("/countries")
async def list_countries(
    db: ReadDBSession,
    token: CurrentToken,
    limit: int = Query(100, ge=1, le=500),
    offset: int = 0,
):
    stmt = select(Country).order_by(Country.name).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(c.id),
            "code": c.code_iso2,
            "name": c.name,
            "region": c.region,
            "currency": c.currency,
        }
        for c in rows
    ]


@router.get("/evaluate/{order_id}")
async def evaluate(
    order_id: str,
    db: ReadDBSession,
    token: CurrentToken,
):
    order = (await db.execute(
        select(Order)
        .options(
            selectinload(Order.vessel),
            selectinload(Order.port),
            selectinload(Order.items)
            .selectinload(OrderItem.product)
            .selectinload(Product.category),
        )
        .where(Order.id == order_id)
    )).scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    issues = await evaluate_order(db, order)
    return {
        "order_id": order_id,
        "summary": summarize(issues),
        "blocking": has_blocking_issue(issues),
        "issues": [
            {
                "severity": i.severity,
                "title": i.title,
                "description": i.description,
                "source": i.source,
                "can_override": i.can_override,
                "legal_reference": i.legal_reference,
                "requires_permit": i.requires_permit,
                "permit_authority": i.permit_authority,
                "permit_lead_time_days": i.permit_lead_time_days,
                "matched_product_ids": i.matched_product_ids or [],
                "rule_id": i.rule_id,
            }
            for i in issues
        ],
    }


@router.get("/rules")
async def list_rules(
    db: ReadDBSession,
    token: CurrentToken,
    country: str | None = Query(None, description="ISO2 country code"),
    severity: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = 0,
):
    stmt = select(CustomsRule).options(selectinload(CustomsRule.country)).order_by(CustomsRule.effective_from.desc())
    if country:
        stmt = stmt.join(Country, Country.id == CustomsRule.country_id).where(Country.code_iso2 == country.upper())
    if severity:
        stmt = stmt.where(CustomsRule.severity == severity)
    stmt = stmt.limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(r.id),
            "country_id": str(r.country_id),
            "country_code": r.country.code_iso2 if r.country else None,
            "name": r.name,
            "description": r.description,
            "severity": r.severity.value,
            "category": r.category.value,
            "hs_code_pattern": r.hs_code_pattern,
            "product_categories": r.product_categories or [],
            "action": r.action,
            "effective_from": r.effective_from.isoformat(),
            "effective_until": r.effective_until.isoformat() if r.effective_until else None,
        }
        for r in rows
    ]


@router.get("/port-regulations")
async def list_port_regulations(
    db: ReadDBSession,
    token: CurrentToken,
    port_id: str | None = Query(None),
    country: str | None = Query(None),
    severity: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = 0,
):
    stmt = select(PortRegulation).order_by(PortRegulation.effective_from.desc())
    if port_id:
        stmt = stmt.where(PortRegulation.port_id == port_id)
    if country:
        stmt = stmt.join(Country, Country.id == PortRegulation.country_id).where(Country.code_iso2 == country.upper())
    if severity:
        stmt = stmt.where(PortRegulation.severity == severity)
    stmt = stmt.limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(r.id),
            "port_id": str(r.port_id),
            "country_id": str(r.country_id),
            "title": r.title,
            "description": r.description,
            "severity": r.severity.value,
            "category": r.category.value,
            "applies_to_categories": r.applies_to_categories or [],
            "applies_to_hs_codes": r.applies_to_hs_codes or [],
            "requires_permit": r.requires_permit,
            "permit_authority": r.permit_authority,
            "effective_from": r.effective_from.isoformat(),
            "effective_until": r.effective_until.isoformat() if r.effective_until else None,
        }
        for r in rows
    ]

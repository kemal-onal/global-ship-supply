"""Catering routes — nationality targets, plan generation, menu templates."""
from datetime import date as date_type
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.deps.auth import CurrentToken, DBSession, ReadDBSession, require_role
from app.models.catering import (
    CrewNationality,
    CrewNationalityEnum,
    DailyMenu,
    MenuTemplate,
    ProvisioningPlan,
)
from app.models.vessel import Vessel
from app.services.catering import compute_voyage_plan, daily_targets

router = APIRouter()


@router.get("/nationalities")
async def list_nationalities(
    db: ReadDBSession,
    token = Depends(require_role("super_admin", "fleet_admin", "vessel_captain", "chief_steward")),
):
    rows = (await db.execute(select(CrewNationality).order_by(CrewNationality.name))).scalars().all()
    return [
        {
            "code": n.code.value,
            "name": n.name,
            "calorie_target": n.calorie_target,
            "protein_pct": n.protein_pct,
            "carb_pct": n.carb_pct,
            "fat_pct": n.fat_pct,
            "preferred_diet_flags": n.preferred_diet_flags or [],
            "preferred_categories": n.preferred_categories or [],
        }
        for n in rows
    ]


@router.get("/menus")
async def list_menu_templates(
    db: ReadDBSession,
    token = Depends(require_role("super_admin", "fleet_admin", "vessel_captain", "chief_steward")),
    nationality: CrewNationalityEnum | None = None,
):
    stmt = select(MenuTemplate).order_by(MenuTemplate.nationality, MenuTemplate.meal_type)
    if nationality:
        stmt = stmt.where(MenuTemplate.nationality == nationality)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(m.id),
            "name": m.name,
            "nationality": m.nationality.value,
            "meal_type": m.meal_type.value,
            "target_kcal": m.target_kcal,
            "is_default": m.is_default,
            "diet_flags": m.diet_flags or [],
        }
        for m in rows
    ]


@router.get("/provisioning-plans")
async def list_plans(
    db: ReadDBSession,
    token = Depends(require_role("super_admin", "fleet_admin", "vessel_captain", "chief_steward")),
    vessel_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    stmt = select(ProvisioningPlan).order_by(ProvisioningPlan.created_at.desc())
    if vessel_id:
        stmt = stmt.where(ProvisioningPlan.vessel_id == vessel_id)
    stmt = stmt.limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(p.id),
            "vessel_id": str(p.vessel_id),
            "name": p.name,
            "voyage_start": p.voyage_start.isoformat(),
            "voyage_end": p.voyage_end.isoformat(),
            "crew_count": p.crew_count,
            "crew_breakdown": p.crew_breakdown,
            "total_kcal": float(p.total_kcal),
            "estimated_cost": float(p.estimated_cost),
            "item_count": len(p.items),
        }
        for p in rows
    ]


@router.get("/provisioning-plans/{plan_id}")
async def get_plan(
    plan_id: str,
    db: ReadDBSession,
    token = Depends(require_role("super_admin", "fleet_admin", "vessel_captain", "chief_steward")),
):
    p = (await db.execute(select(ProvisioningPlan).where(ProvisioningPlan.id == plan_id))).scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Plan not found")
    return {
        "id": str(p.id),
        "vessel_id": str(p.vessel_id),
        "name": p.name,
        "voyage_start": p.voyage_start.isoformat(),
        "voyage_end": p.voyage_end.isoformat(),
        "crew_count": p.crew_count,
        "crew_breakdown": p.crew_breakdown,
        "buffer_days": p.buffer_days,
        "buffer_pct": p.buffer_pct,
        "total_kcal": float(p.total_kcal),
        "estimated_cost": float(p.estimated_cost),
        "items": [
            {
                "product_id": str(i.product_id),
                "product_name": i.product.name if i.product else None,
                "product_sku": i.product.sku if i.product else None,
                "required_qty": float(i.required_qty),
                "unit": i.unit,
                "unit_price": float(i.unit_price),
                "line_total": float(i.line_total),
                "per_day_grams": float(i.per_day_grams) if i.per_day_grams else None,
            }
            for i in p.items
        ],
    }


class GeneratePlanIn(BaseModel):
    vessel_id: str
    voyage_start: date_type
    voyage_end: date_type
    crew_breakdown: dict[str, int] = Field(description='e.g. {"filipino": 12, "indian": 8}')
    buffer_days: Optional[int] = None
    buffer_pct: Optional[float] = None
    name: Optional[str] = None


@router.post("/provisioning-plans")
async def generate_plan(
    payload: GeneratePlanIn,
    db: DBSession,
    token = Depends(require_role("super_admin", "fleet_admin", "vessel_captain", "chief_steward")),
):
    vessel = (await db.execute(select(Vessel).where(Vessel.id == payload.vessel_id))).scalar_one_or_none()
    if not vessel:
        raise HTTPException(status_code=404, detail="Vessel not found")
    try:
        plan = await compute_voyage_plan(
            db, vessel,
            voyage_start=payload.voyage_start,
            voyage_end=payload.voyage_end,
            crew_breakdown=payload.crew_breakdown,
            buffer_days=payload.buffer_days,
            buffer_pct=payload.buffer_pct,
            name=payload.name,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    db.add(plan)
    await db.commit()
    await db.refresh(plan)
    return {
        "id": str(plan.id),
        "name": plan.name,
        "total_kcal": float(plan.total_kcal),
        "estimated_cost": float(plan.estimated_cost),
        "item_count": len(plan.items),
    }


@router.post("/compute-targets")
async def compute_targets(
    payload: dict,
    token = Depends(require_role("super_admin", "fleet_admin", "vessel_captain", "chief_steward")),
):
    """Pure helper — compute daily calorie targets for a crew breakdown
    using the configured default per-person target."""
    breakdown = payload.get("crew_breakdown", {})
    return daily_targets(breakdown)


class GeneratePlanSimpleIn(BaseModel):
    vessel_id: str
    start_date: date_type
    end_date: date_type
    crew_by_nationality: dict[str, int] = Field(default_factory=dict)


@router.post("/plan")
async def generate_plan_simple(
    payload: GeneratePlanSimpleIn,
    db: DBSession,
    token = Depends(require_role("super_admin", "fleet_admin", "vessel_captain", "chief_steward")),
):
    """Frontend-friendly alias of /provisioning-plans.

    Accepts ISO date strings and a flat crew_by_nationality dict, and
    returns the basket inline (without persisting) so the UI can show
    a preview before the steward commits.
    """
    vessel = (await db.execute(select(Vessel).where(Vessel.id == payload.vessel_id))).scalar_one_or_none()
    if not vessel:
        raise HTTPException(status_code=404, detail="Vessel not found")
    if not payload.crew_by_nationality:
        raise HTTPException(status_code=400, detail="crew_by_nationality is required")

    try:
        plan = await compute_voyage_plan(
            db, vessel,
            voyage_start=payload.start_date,
            voyage_end=payload.end_date,
            crew_breakdown=payload.crew_by_nationality,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # Inline preview — don't persist
    items = []
    for it in plan.items:
        items.append({
            "product_id": str(it.product_id),
            "sku": it.product.sku if it.product else None,
            "name": it.product.name if it.product else None,
            "category": it.product.category.code if it.product and it.product.category else None,
            "quantity": float(it.required_qty),
            "unit": it.unit,
            "unit_price": float(it.unit_price),
            "estimated_cost": float(it.line_total),
            "currency": "USD",
        })

    total_crew = sum(payload.crew_by_nationality.values())
    days = (payload.end_date - payload.start_date).days + 1

    return {
        "id": str(plan.id),
        "vessel_id": str(plan.vessel_id),
        "voyage_start": plan.voyage_start.isoformat(),
        "voyage_end": plan.voyage_end.isoformat(),
        "days": days,
        "total_crew": total_crew,
        "total_calories": float(plan.total_kcal),
        "daily_average": float(plan.total_kcal) / max(days, 1),
        "estimated_cost": float(plan.estimated_cost),
        "items": items,
    }

"""
Catering & Calorie Management service.

Workflow:
1. Chief steward defines a crew breakdown (nationalities + headcount).
2. Service computes total daily calorie target.
3. Picks menu templates (one per meal type per nationality) and aggregates the
   required products into a ProvisioningPlan.
4. Adds buffer days and percentage to cover voyage duration.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.catering import (
    CrewNationality,
    CrewNationalityEnum,
    MealType,
    MenuTemplate,
    ProvisioningItem,
    ProvisioningPlan,
)
from app.models.product import Product
from app.models.vessel import Vessel


# Per-meal calorie distribution (out of 1.0) — typical shipboard schedule.
MEAL_DISTRIBUTION: dict[MealType, float] = {
    MealType.BREAKFAST: 0.25,
    MealType.LUNCH: 0.30,
    MealType.DINNER: 0.30,
    MealType.SNACK: 0.10,
    MealType.MIDNIGHT: 0.05,
}


async def compute_voyage_plan(
    db: AsyncSession,
    vessel: Vessel,
    voyage_start: date,
    voyage_end: date,
    crew_breakdown: dict[str, int],
    *,
    buffer_days: int | None = None,
    buffer_pct: float | None = None,
    name: str | None = None,
) -> ProvisioningPlan:
    """Create a provisioning plan from a crew breakdown and voyage dates."""
    buffer_days = buffer_days if buffer_days is not None else settings.PROVISIONING_BUFFER_DAYS
    buffer_pct = buffer_pct if buffer_pct is not None else settings.PROVISIONING_BUFFER_PERCENT
    total_days = (voyage_end - voyage_start).days + buffer_days
    if total_days <= 0:
        raise ValueError("voyage_end must be after voyage_start")

    # 1) Validate nationalities and compute target calories/day
    total_crew = sum(crew_breakdown.values())
    if total_crew <= 0:
        raise ValueError("crew_breakdown must sum to > 0")

    breakdown_normalized: dict[CrewNationalityEnum, int] = {}
    total_kcal_per_day = 0.0
    for code, headcount in crew_breakdown.items():
        nat = await db.execute(
            select(CrewNationality).where(CrewNationality.code == CrewNationalityEnum(code))
        )
        nat_row = nat.scalar_one_or_none()
        if not nat_row:
            raise ValueError(f"Unknown nationality: {code}")
        breakdown_normalized[nat_row.code] = headcount
        total_kcal_per_day += nat_row.calorie_target * headcount

    # 2) Pick menu templates: one per (nationality, meal_type)
    plan = ProvisioningPlan(
        vessel_id=vessel.id,
        name=name or f"{vessel.name} voyage {voyage_start.isoformat()} – {voyage_end.isoformat()}",
        voyage_start=voyage_start,
        voyage_end=voyage_end,
        crew_count=total_crew,
        crew_breakdown={k.value: v for k, v in breakdown_normalized.items()},
        buffer_days=buffer_days,
        buffer_pct=buffer_pct,
    )

    # Map (nationality, meal_type) -> target kcal/person
    aggregated: dict[tuple[str, str], float] = defaultdict(float)
    for nat_code, headcount in breakdown_normalized.items():
        nat = (await db.execute(
            select(CrewNationality).where(CrewNationality.code == nat_code)
        )).scalar_one()
        daily_target = nat.calorie_target
        for meal_type, frac in MEAL_DISTRIBUTION.items():
            aggregated[(nat_code.value, meal_type.value)] += headcount * daily_target * frac

    # 3) Resolve templates
    product_needs: dict[tuple[str, str, str], float] = defaultdict(float)  # (product_id, unit) -> grams
    product_meta: dict[str, Product] = {}
    for (nat_value, meal_value), kcal_needed in aggregated.items():
        tpl = (await db.execute(
            select(MenuTemplate).where(
                MenuTemplate.nationality == CrewNationalityEnum(nat_value),
                MenuTemplate.meal_type == MealType(meal_value),
                MenuTemplate.is_default.is_(True),
            )
        )).scalar_one_or_none()
        if not tpl:
            continue
        for mi in tpl.items:
            # Each menu item serves ~1 person; total servings = headcount * days
            servings_per_day = aggregated[(nat_value, meal_value)] / max(tpl.target_kcal, 1)
            total_grams = mi.serving_grams * servings_per_day * total_days
            product_needs[(str(mi.product_id), mi.product.unit.value)] += total_grams
            product_meta[str(mi.product_id)] = mi.product

    # 4) Convert grams to purchase units, apply buffer
    items: list[ProvisioningItem] = []
    total_cost = 0.0
    for (product_id, unit), grams in product_needs.items():
        product = product_meta[product_id]
        qty_in_purchase_unit = grams / 1000.0 if product.unit.value in ("kg",) else grams
        # Apply buffer
        qty_with_buffer = qty_in_purchase_unit * (1 + buffer_pct)
        # Round up to sensible precision
        line_total = float(qty_with_buffer) * float(product.unit_price)
        items.append(ProvisioningItem(
            product_id=product.id,
            required_qty=round(qty_with_buffer, 3),
            unit=unit,
            unit_price=product.unit_price,
            line_total=round(line_total, 4),
            per_day_grams=round(grams / total_days, 2),
        ))
        total_cost += line_total

    plan.total_kcal = round(total_kcal_per_day * total_days, 2)
    plan.estimated_cost = round(total_cost, 2)
    plan.items = items
    return plan


def daily_targets(crew_breakdown: dict[str, int]) -> dict[str, Any]:
    """Pure helper — no DB. Returns the calorie target breakdown by nationality."""
    out = {}
    for code, headcount in crew_breakdown.items():
        try:
            enum_code = CrewNationalityEnum(code)
        except ValueError:
            continue
        # Use the canonical default if no DB hit
        default_kcal = settings.CALORIE_TARGET_PER_PERSON_PER_DAY
        out[code] = {
            "headcount": headcount,
            "kcal_per_person_per_day": default_kcal,
            "total_kcal_per_day": default_kcal * headcount,
        }
    return out

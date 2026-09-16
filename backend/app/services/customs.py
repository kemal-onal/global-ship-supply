"""
Customs / Port Regulation filter.

Given a vessel's destination port and an order (with line items), this service
returns a list of warnings/blockers describing regulatory issues.

The rule engine:
* Loads all active PortRegulations and CustomsRules for the destination country
* Filters by `applies_to_categories`, `applies_to_hs_codes`, `applies_to_impa_codes`,
  `applies_to_vessel_types`, `applies_to_flags`
* Optionally evaluates `condition_expression` (JSONLogic) — we only support a
  minimal subset in this MVP
* Returns an annotated list with severity, title, description, blocker flag
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order, OrderItem
from app.models.port import Country, CustomsRule, PortRegulation, RegulationSeverity
from app.models.product import Product
from app.models.vessel import Vessel


@dataclass
class RegulationIssue:
    severity: str
    title: str
    description: str
    source: str
    can_override: bool
    legal_reference: str | None = None
    requires_permit: bool = False
    permit_authority: str | None = None
    permit_lead_time_days: int | None = None
    matched_product_ids: list[str] | None = None
    rule_id: str | None = None


def _check_applicability(rule: PortRegulation, product: Product, vessel: Vessel) -> bool:
    """Check whether a regulation rule applies to a given product/vessel pair."""
    if rule.applies_to_categories:
        cats = product.tags or []
        if not any(c in cats for c in rule.applies_to_categories):
            if product.category.code not in rule.applies_to_categories:
                return False
    if rule.applies_to_hs_codes:
        if not product.hs_code or not any(
            product.hs_code.startswith(p) for p in rule.applies_to_hs_codes
        ):
            return False
    if rule.applies_to_vessel_types:
        if vessel.vessel_type.value not in rule.applies_to_vessel_types:
            return False
    if rule.applies_to_flags:
        if not vessel.flag_state or vessel.flag_state not in rule.applies_to_flags:
            return False
    return True


def _is_active(rule: PortRegulation | CustomsRule, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    if rule.effective_from > now:
        return False
    if rule.effective_until and rule.effective_until < now:
        return False
    if hasattr(rule, "is_permanent") and getattr(rule, "is_permanent", False):
        return True
    return True


def _eval_condition(expr: dict | None, context: dict) -> bool:
    """Tiny JSONLogic-like evaluator — supports a useful subset."""
    if not expr:
        return True
    if not isinstance(expr, dict) or len(expr) != 1:
        return False
    op, args = next(iter(expr.items()))
    if op == "==":
        if not isinstance(args, list) or len(args) != 2:
            return False
        return _resolve(args[0], context) == _resolve(args[1], context)
    if op == "in":
        if not isinstance(args, list) or len(args) != 2:
            return False
        return _resolve(args[0], context) in _resolve(args[1], context)
    if op == "and":
        return all(_eval_condition(a, context) for a in (args or []))
    if op == "or":
        return any(_eval_condition(a, context) for a in (args or []))
    if op == ">":
        if not isinstance(args, list) or len(args) != 2:
            return False
        return _resolve(args[0], context) > _resolve(args[1], context)
    if op == "<":
        if not isinstance(args, list) or len(args) != 2:
            return False
        return _resolve(args[0], context) < _resolve(args[1], context)
    if op == ">=":
        if not isinstance(args, list) or len(args) != 2:
            return False
        return _resolve(args[0], context) >= _resolve(args[1], context)
    if op == "<=":
        if not isinstance(args, list) or len(args) != 2:
            return False
        return _resolve(args[0], context) <= _resolve(args[1], context)
    return False


def _resolve(value: Any, context: dict) -> Any:
    if isinstance(value, dict) and "var" in value:
        return context.get(value["var"])
    return value


async def evaluate_order(
    db: AsyncSession,
    order: Order,
    *,
    include_country_rules: bool = True,
) -> list[RegulationIssue]:
    """Return all regulation issues for an order's destination port."""
    vessel = order.vessel
    port = order.port
    if not vessel or not port:
        return []

    # Load port-specific regulations
    port_rules = (await db.execute(
        select(PortRegulation).where(
            PortRegulation.port_id == port.id,
            PortRegulation.is_deleted.is_(False),
        )
    )).scalars().all()

    # Country-level customs rules
    country_rules: list[CustomsRule] = []
    if include_country_rules:
        country_rules = (await db.execute(
            select(CustomsRule).where(
                CustomsRule.country_id == port.country_id,
                CustomsRule.is_deleted.is_(False),
            )
        )).scalars().all()

    # Build context for condition expressions
    items_meta: list[dict] = []
    for oi in order.items:
        p = oi.product
        if not p:
            continue
        items_meta.append({
            "product_id": str(p.id),
            "hs_code": p.hs_code or "",
            "category": p.category.code if p.category else "",
            "tags": p.tags or [],
            "is_hazardous": p.is_hazardous,
            "is_perishable": p.is_perishable,
            "name": p.name,
            "sku": p.sku,
        })
    context = {
        "vessel_type": vessel.vessel_type.value,
        "flag_state": vessel.flag_state or "",
        "vessel_imo": vessel.imo_number,
        "port": port.unlocode,
        "items": items_meta,
        "total": float(order.grand_total),
    }

    issues: list[RegulationIssue] = []

    # 1) Port-level rules
    for rule in port_rules:
        if not _is_active(rule):
            continue
        matched: list[str] = []
        for oi in order.items:
            if not oi.product:
                continue
            if _check_applicability(rule, oi.product, vessel):
                if _eval_condition(json.loads(rule.condition_expression) if rule.condition_expression else None, {**context, "item": next(i for i in items_meta if i["product_id"] == str(oi.product_id))}):
                    matched.append(str(oi.product_id))
        if not matched and (rule.applies_to_categories or rule.applies_to_hs_codes or rule.applies_to_impa_codes or rule.applies_to_vessel_types or rule.applies_to_flags):
            # No product matched — skip
            continue
        if not matched:
            # Generic rule applied to whole order
            matched = [str(oi.product_id) for oi in order.items]
        issues.append(RegulationIssue(
            severity=rule.severity.value,
            title=rule.title,
            description=rule.description,
            source="port",
            can_override=rule.can_override,
            legal_reference=rule.legal_reference,
            requires_permit=rule.requires_permit,
            permit_authority=rule.permit_authority,
            permit_lead_time_days=rule.permit_lead_time_days,
            matched_product_ids=matched,
            rule_id=str(rule.id),
        ))

    # 2) Country-level customs rules
    for rule in country_rules:
        if not _is_active(rule):
            continue
        matched: list[str] = []
        for oi in order.items:
            p = oi.product
            if not p:
                continue
            if rule.hs_code_pattern and p.hs_code and p.hs_code.startswith(rule.hs_code_pattern.split(".")[0]):
                matched.append(str(p.id))
            elif rule.product_categories and p.category.code in rule.product_categories:
                matched.append(str(p.id))
            elif rule.impa_code_pattern and p.impa_code and p.impa_code.code.startswith(rule.impa_code_pattern):
                matched.append(str(p.id))
        if not matched:
            continue
        issues.append(RegulationIssue(
            severity=rule.severity.value,
            title=rule.name,
            description=rule.description,
            source="customs",
            can_override=True,
            legal_reference=None,
            requires_permit=rule.action == "require_permit",
            permit_authority=rule.action_params.get("permit_type") if rule.action_params else None,
            permit_lead_time_days=None,
            matched_product_ids=matched,
            rule_id=str(rule.id),
        ))

    return issues


def has_blocking_issue(issues: list[RegulationIssue]) -> bool:
    return any(i.severity in (RegulationSeverity.BLOCKING.value, RegulationSeverity.PROHIBITED.value) for i in issues)


def summarize(issues: list[RegulationIssue]) -> dict[str, int]:
    summary: dict[str, int] = {"info": 0, "warning": 0, "restricted": 0, "prohibited": 0, "blocking": 0}
    for i in issues:
        key = i.severity if i.severity in summary else "warning"
        summary[key] = summary.get(key, 0) + 1
    return summary

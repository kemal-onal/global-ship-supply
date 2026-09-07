"""
Catalog routes — product search, IMPA/ISSA cross-reference, categories.

The search endpoint is the heart of the platform. It uses:
* B+ tree indexes (PostgreSQL default) over sku, category_id, status, price
* GIN indexes over tsvector columns for full-text search
"""
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps.auth import CurrentToken, ReadDBSession, require_permission
from app.models.product import (
    ImpaCode,
    IssaCode,
    Product,
    ProductCategory,
    ProductStatus,
)
from app.models.supplier import ProductSupplier
from app.services.redaction import (
    hides_prices,
    seal_catalog_for_purchaser,
    seal_product_for_purchaser,
)
from app.services.search import SearchFilters, search_products

router = APIRouter()


@router.get("/products")
async def list_products(
    db: ReadDBSession,
    token: CurrentToken,
    q: str | None = Query(None, description="Full-text search query"),
    category_id: str | None = Query(None),
    status: ProductStatus | None = Query(None),
    min_price: float | None = Query(None, ge=0),
    max_price: float | None = Query(None, ge=0),
    in_stock: bool | None = Query(None),
    manufacturer: str | None = Query(None),
    impa_code: str | None = Query(None),
    issa_code: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    sort: str = Query("relevance", pattern="^(relevance|name|price_asc|price_desc|newest)$"),
):
    """Search and filter the IMPA/ISSA product catalog."""
    filters = SearchFilters(
        q=q,
        category_id=category_id,
        status=status,
        min_price=min_price,
        max_price=max_price,
        in_stock=in_stock,
        manufacturer=manufacturer,
        impa_code=impa_code,
        issa_code=issa_code,
        limit=limit,
        offset=offset,
        sort=sort,
    )
    result = await search_products(db, filters)
    # The purchaser's view strips every price — the OrderCreate cart
    # can't pre-fill a unit_price from the catalog if the API leaks
    # one, and the catalog page must show "—" for the price column.
    if hides_prices(token.roles):
        return seal_catalog_for_purchaser(result)
    return result


@router.get("/rfq-eligible")
async def list_rfq_eligible(
    db: ReadDBSession,
    token: CurrentToken,
    min_suppliers: int = Query(2, ge=1, le=20, description="Minimum distinct suppliers per product"),
    q: str | None = Query(None, description="Optional name/SKU substring filter"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Products that can actually trigger a bid war.

    Filters down to in-stock, ACTIVE products that have at least
    `min_suppliers` distinct suppliers offering them. This is the
    curated list surfaced in the New-Order product picker so a
    purchasing officer can't pick a product nobody can quote on.

    Each row includes `supplier_count` (the number of suppliers
    currently able to bid) so the UI can sort/badgify it.
    """
    # Subquery: products grouped by supplier count, filtered to >=min
    sq = (
        select(
            ProductSupplier.product_id.label("pid"),
            func.count(func.distinct(ProductSupplier.supplier_id)).label("sc"),
        )
        .group_by(ProductSupplier.product_id)
        .having(func.count(func.distinct(ProductSupplier.supplier_id)) >= min_suppliers)
        .subquery()
    )

    total = (await db.execute(
        select(func.count())
        .select_from(Product)
        .join(sq, sq.c.pid == Product.id)
        .where(Product.is_deleted.is_(False))
        .where(Product.in_stock.is_(True))
        .where(Product.status == ProductStatus.ACTIVE)
    )).scalar_one()

    stmt = (
        select(
            Product.id,
            Product.sku,
            Product.name,
            Product.short_name,
            Product.unit_price,
            Product.currency,
            Product.unit,
            Product.in_stock,
            Product.stock_qty,
            Product.lead_time_days,
            Product.manufacturer,
            sq.c.sc.label("supplier_count"),
        )
        .join(sq, sq.c.pid == Product.id)
        .where(Product.is_deleted.is_(False))
        .where(Product.in_stock.is_(True))
        .where(Product.status == ProductStatus.ACTIVE)
        .order_by(sq.c.sc.desc(), Product.name.asc())
        .limit(limit)
        .offset(offset)
    )
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Product.name.ilike(like), Product.sku.ilike(like)))

    rows = (await db.execute(stmt)).mappings().all()
    # Normalize Decimal to float + enum to string so the JSON response is plain
    items = []
    for r in rows:
        items.append({
            "id": str(r["id"]),
            "sku": r["sku"],
            "name": r["name"],
            "short_name": r["short_name"],
            "unit_price": float(r["unit_price"]),
            "currency": r["currency"],
            "unit": r["unit"].value if hasattr(r["unit"], "value") else r["unit"],
            "in_stock": r["in_stock"],
            "stock_qty": r["stock_qty"],
            "lead_time_days": r["lead_time_days"],
            "manufacturer": r["manufacturer"],
            "supplier_count": int(r["supplier_count"]),
        })
    result = {"items": items, "total": total, "min_suppliers": min_suppliers}
    if hides_prices(token.roles):
        return seal_catalog_for_purchaser(result)
    return result


@router.get("/products/{product_id}")
async def get_product(
    product_id: str,
    db: ReadDBSession,
    token: CurrentToken,
):
    p = (await db.execute(select(Product).where(Product.id == product_id))).scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")
    payload = {
        "id": str(p.id),
        "sku": p.sku,
        "name": p.name,
        "short_name": p.short_name,
        "description": p.description,
        "category_id": str(p.category_id),
        "category_code": p.category.code if p.category else None,
        "status": p.status.value,
        "unit_price": float(p.unit_price),
        "currency": p.currency,
        "unit": p.unit.value,
        "in_stock": p.in_stock,
        "stock_qty": p.stock_qty,
        "lead_time_days": p.lead_time_days,
        "manufacturer": p.manufacturer,
        "part_number": p.part_number,
        "hs_code": p.hs_code,
        "barcode": p.barcode,
        "is_hazardous": p.is_hazardous,
        "is_perishable": p.is_perishable,
        "shelf_life_days": p.shelf_life_days,
        "tags": p.tags or [],
        "impa_code": p.impa_code.code if p.impa_code else None,
        "issa_code": p.issa_code.code if p.issa_code else None,
        "weight_kg": float(p.weight_kg) if p.weight_kg else None,
        "dimensions": p.dimensions,
        "specifications": [
            {
                "key": s.key,
                "value": s.value,
                "unit": s.unit,
            }
            for s in p.specifications
        ],
    }
    if hides_prices(token.roles):
        return seal_product_for_purchaser(payload)
    return payload


@router.get("/categories")
async def list_categories(
    db: ReadDBSession,
    token: CurrentToken,
):
    rows = (await db.execute(
        select(ProductCategory).order_by(ProductCategory.sort_order, ProductCategory.name)
    )).scalars().all()
    return [
        {
            "id": str(c.id),
            "code": c.code,
            "name": c.name,
            "parent_id": str(c.parent_id) if c.parent_id else None,
            "description": c.description,
            "icon": c.icon,
            "default_unit": c.default_unit.value,
        }
        for c in rows
    ]


@router.get("/impa")
async def list_impa(
    db: ReadDBSession,
    token: CurrentToken,
    q: str | None = Query(None),
    group: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    stmt = select(ImpaCode).order_by(ImpaCode.code)
    if q:
        like = f"%{q}%"
        stmt = stmt.where((ImpaCode.code.ilike(like)) | (ImpaCode.name.ilike(like)))
    if group:
        stmt = stmt.where(ImpaCode.group_code == group)
    stmt = stmt.limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()
    return [{"code": r.code, "name": r.name, "description": r.description, "group": r.group_code} for r in rows]


class ImpaLookupIn(BaseModel):
    """Body for the bulk IMPA lookup.

    Why bulk: a single order can have 5-20 lines, and a supplier's
    quote form might render 30+ lines. Per-code round trips
    (N+1) would be wasteful. The frontend batches the codes on
    the page into one POST.
    """
    codes: list[str] = Field(min_length=1, max_length=500)


@router.post("/impa/lookup")
async def lookup_impa(
    payload: ImpaLookupIn,
    db: ReadDBSession,
    token: CurrentToken,
):
    """Bulk-resolve IMPA codes to their human names.

    The IMPA-first redesign: the **vessel** side types a 6-digit
    IMPA code, but the **supplier** side doesn't know what those
    codes mean. The company (admin) is the bridge — and the
    platform's job is to translate the code into a name wherever
    it's rendered. This endpoint powers that translation.

    Behaviour:
      * Returns one entry per requested code, in the same order.
      * Unknown codes get `name: null` (not 404) so the UI can
        gracefully render "code: 999999 (not in catalog)" without
        a per-line error state.
      * Whitespace is stripped; empty strings are filtered out
        before the DB query but preserved in the response with
        `name: null` so the caller can index by position.
    """
    # Dedupe + strip + filter empties for the DB query, but keep
    # the original list (with empties) so the response order
    # matches the request.
    requested = [c.strip() if c else "" for c in payload.codes]
    seen: set[str] = set()
    query_codes: list[str] = []
    for c in requested:
        if c and c not in seen:
            seen.add(c)
            query_codes.append(c)
    if not query_codes:
        return [{"code": c, "name": None, "group": None} for c in requested]

    rows = (await db.execute(
        select(ImpaCode).where(ImpaCode.code.in_(query_codes))
    )).scalars().all()
    by_code = {r.code: r for r in rows}

    return [
        {
            "code": c,
            "name": by_code[c].name if c in by_code else None,
            "group": by_code[c].group_code if c in by_code else None,
        }
        for c in requested
    ]


@router.get("/issa")
async def list_issa(
    db: ReadDBSession,
    token: CurrentToken,
    q: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    stmt = select(IssaCode).order_by(IssaCode.code)
    if q:
        like = f"%{q}%"
        stmt = stmt.where((IssaCode.code.ilike(like)) | (IssaCode.name.ilike(like)))
    stmt = stmt.limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()
    return [{"code": r.code, "name": r.name, "description": r.description} for r in rows]


@router.get("/stats")
async def catalog_stats(
    db: ReadDBSession,
    token: CurrentToken,
):
    total = (await db.execute(select(func.count()).select_from(Product).where(Product.is_deleted.is_(False)))).scalar_one()
    by_status = (await db.execute(
        select(Product.status, func.count()).where(Product.is_deleted.is_(False)).group_by(Product.status)
    )).all()
    by_category = (await db.execute(
        select(ProductCategory.code, ProductCategory.name, func.count(Product.id))
        .join(Product, Product.category_id == ProductCategory.id)
        .where(Product.is_deleted.is_(False))
        .group_by(ProductCategory.code, ProductCategory.name)
    )).all()
    return {
        "total_products": total,
        "by_status": {s.value: c for s, c in by_status},
        "by_category": [{"code": code, "name": name, "count": c} for code, name, c in by_category],
    }

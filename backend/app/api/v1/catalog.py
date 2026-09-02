"""
Catalog routes — product search, IMPA/ISSA cross-reference, categories.

The search endpoint is the heart of the platform. It uses:
* B+ tree indexes (PostgreSQL default) over sku, category_id, status, price
* GIN indexes over tsvector columns for full-text search
"""
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps.auth import CurrentToken, ReadDBSession, require_permission
from app.models.product import (
    ImpaCode,
    IssaCode,
    Product,
    ProductCategory,
    ProductStatus,
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
    return await search_products(db, filters)


@router.get("/products/{product_id}")
async def get_product(
    product_id: str,
    db: ReadDBSession,
    token: CurrentToken,
):
    p = (await db.execute(select(Product).where(Product.id == product_id))).scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")
    return {
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

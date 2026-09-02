"""Port routes — list, get, country info."""
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import or_, select

from app.deps.auth import CurrentToken, ReadDBSession
from app.models.port import Country, Port, PortStatus

router = APIRouter()


@router.get("")
async def list_ports(
    db: ReadDBSession,
    token: CurrentToken,
    q: str | None = Query(None),
    country: str | None = Query(None, description="ISO2 country code"),
    status: PortStatus | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    from sqlalchemy.orm import selectinload
    stmt = select(Port).options(selectinload(Port.country)).order_by(Port.name)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Port.name.ilike(like), Port.unlocode.ilike(like)))
    if country:
        stmt = stmt.join(Country, Country.id == Port.country_id).where(Country.code_iso2 == country.upper())
    if status:
        stmt = stmt.where(Port.status == status)
    stmt = stmt.limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(p.id),
            "unlocode": p.unlocode,
            "name": p.name,
            "country": p.country.code_iso2 if p.country else None,
            "country_name": p.country.name if p.country else None,
            "latitude": p.latitude,
            "longitude": p.longitude,
            "port_type": p.port_type.value,
            "status": p.status.value,
            "has_bunkering": p.has_bunkering,
            "has_fresh_water": p.has_fresh_water,
            "has_provisions": p.has_provisions,
            "has_chandler": p.has_chandler,
            "has_repair": p.has_repair,
            "has_medical": p.has_medical,
            "max_vessel_loa": p.max_vessel_loa,
            "max_vessel_beam": p.max_vessel_beam,
            "max_draft": p.max_draft,
        }
        for p in rows
    ]


@router.get("/{port_id}")
async def get_port(
    port_id: str,
    db: ReadDBSession,
    token: CurrentToken,
):
    p = (await db.execute(select(Port).where(Port.id == port_id))).scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Port not found")
    return {
        "id": str(p.id),
        "unlocode": p.unlocode,
        "name": p.name,
        "country_id": str(p.country_id),
        "country_name": p.country.name if p.country else None,
        "latitude": p.latitude,
        "longitude": p.longitude,
        "timezone": p.timezone,
        "port_type": p.port_type.value,
        "status": p.status.value,
        "operating_hours": p.operating_hours,
        "max_vessel_loa": p.max_vessel_loa,
        "max_vessel_beam": p.max_vessel_beam,
        "max_draft": p.max_draft,
        "has_bunkering": p.has_bunkering,
        "has_fresh_water": p.has_fresh_water,
        "has_provisions": p.has_provisions,
        "has_chandler": p.has_chandler,
        "has_repair": p.has_repair,
        "has_medical": p.has_medical,
        "has_waste_reception": p.has_waste_reception,
        "has_shore_power": p.has_shore_power,
        "port_authority": p.port_authority,
        "contact_email": p.contact_email,
        "contact_phone": p.contact_phone,
    }


@router.get("/_/countries")
async def list_countries(
    db: ReadDBSession,
    token: CurrentToken,
):
    rows = (await db.execute(select(Country).order_by(Country.name))).scalars().all()
    return [
        {
            "id": str(c.id),
            "code_iso2": c.code_iso2,
            "code_iso3": c.code_iso3,
            "name": c.name,
            "region": c.region.value,
            "customs_union": c.customs_union,
            "prohibited_categories": c.prohibited_categories or [],
            "requires_halal_cert": c.requires_halal_cert,
            "requires_kosher_cert": c.requires_kosher_cert,
            "currency": c.currency,
        }
        for c in rows
    ]

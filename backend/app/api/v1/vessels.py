"""Vessel routes — list, get, create."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps.auth import CurrentToken, ReadDBSession
from app.models.vessel import Vessel, VesselStatus

router = APIRouter()


@router.get("")
async def list_vessels(
    db: ReadDBSession,
    token: CurrentToken,
    q: str | None = Query(None),
    status: VesselStatus | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    stmt = select(Vessel).order_by(Vessel.name)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Vessel.name.ilike(like), Vessel.imo_number.ilike(like), Vessel.flag_state.ilike(like)))
    if status:
        stmt = stmt.where(Vessel.status == status)
    stmt = stmt.limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(v.id),
            "imo_number": v.imo_number,
            "name": v.name,
            "vessel_type": v.vessel_type.value,
            "flag_state": v.flag_state,
            "owner": v.owner,
            "operator": v.operator,
            "status": v.status.value,
            "crew_capacity": v.crew_capacity,
            "current_crew_count": v.current_crew_count,
            "next_port_id": str(v.next_port_id) if v.next_port_id else None,
            "next_port_eta": v.next_port_eta.isoformat() if v.next_port_eta else None,
        }
        for v in rows
    ]


@router.get("/{vessel_id}")
async def get_vessel(
    vessel_id: str,
    db: ReadDBSession,
    token: CurrentToken,
):
    v = (await db.execute(select(Vessel).where(Vessel.id == vessel_id))).scalar_one_or_none()
    if not v:
        raise HTTPException(status_code=404, detail="Vessel not found")
    return {
        "id": str(v.id),
        "imo_number": v.imo_number,
        "mmsi": v.mmsi,
        "name": v.name,
        "vessel_type": v.vessel_type.value,
        "flag_state": v.flag_state,
        "owner": v.owner,
        "operator": v.operator,
        "status": v.status.value,
        "crew_capacity": v.crew_capacity,
        "current_crew_count": v.current_crew_count,
        "min_safe_manning": v.min_safe_manning,
        "loa": v.loa,
        "beam": v.beam,
        "draft_summer": v.draft_summer,
        "dwt": v.dwt,
        "gt": v.gt,
        "vsat_provider": v.vsat_provider,
        "is_ism_certified": v.is_ism_certified,
        "is_mlc_certified": v.is_mlc_certified,
        "next_port_id": str(v.next_port_id) if v.next_port_id else None,
        "next_port_eta": v.next_port_eta.isoformat() if v.next_port_eta else None,
    }

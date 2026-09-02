"""User routes — list, get, current roles/permissions."""
from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.deps.auth import CurrentToken, ReadDBSession
from app.models.user import User

router = APIRouter()


@router.get("")
async def list_users(
    db: ReadDBSession,
    token: CurrentToken,
    limit: int = 50,
    offset: int = 0,
):
    rows = (await db.execute(select(User).order_by(User.email).limit(limit).offset(offset))).scalars().all()
    return [
        {
            "id": str(u.id),
            "email": u.email,
            "username": u.username,
            "full_name": u.full_name,
            "status": u.status.value,
            "vessel_id": str(u.vessel_id) if u.vessel_id else None,
            "roles": u.get_roles(),
            "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
        }
        for u in rows
    ]


@router.get("/{user_id}")
async def get_user(
    user_id: str,
    db: ReadDBSession,
    token: CurrentToken,
):
    u = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "id": str(u.id),
        "email": u.email,
        "username": u.username,
        "full_name": u.full_name,
        "phone": u.phone,
        "status": u.status.value,
        "vessel_id": str(u.vessel_id) if u.vessel_id else None,
        "email_verified": u.email_verified,
        "two_factor_enabled": u.two_factor_enabled,
        "roles": u.get_roles(),
        "permissions": sorted(u.get_permissions()),
    }

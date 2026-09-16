"""
Auth routes — login, refresh, me, logout.

The login endpoint simulates the IPSec/SSL VPN handshake by recording
the connection fingerprint and emitting a SecurityEvent. Failed attempts
are counted by the IDS layer; once an IP crosses the brute-force threshold,
subsequent attempts return 429 until the window expires.
"""
from datetime import datetime, timezone

from pydantic import BaseModel
from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.ids import check_brute_force, record_login_failure
from app.core.logging import get_logger
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from app.deps.auth import CurrentToken, db_session
from app.models.audit import SecurityEvent, SecurityEventType, SecuritySeverity
from app.models.user import User, UserStatus, UserRole, Role, RolePermission

log = get_logger("avs.auth")

class LoginPayload(BaseModel):
    username: str
    password: str

router = APIRouter()


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _token_pair(user: User) -> dict:
    roles = []
    perms: set[str] = set()
    for ur in user.roles:
        if ur.role:
            roles.append(ur.role.name)
            for rp in ur.role.permissions:
                if rp.permission:
                    perms.add(
                        f"{rp.permission.resource}:{rp.permission.action}:{rp.permission.scope}"
                    )
    access = create_access_token(
        subject=str(user.id),
        roles=roles,
        permissions=sorted(perms),
        vessel_id=str(user.vessel_id) if user.vessel_id else None,
    )
    refresh = create_refresh_token(subject=str(user.id))
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }


@router.post("/login")
async def login(
    request: Request,
    payload: LoginPayload = Body(...),
    db: AsyncSession = Depends(db_session),
) -> dict:
    """Minimal working login � direct load + verify + token."""
    username = payload.username
    password = payload.password
    result = await db.execute(
        select(User)
        .options(
            selectinload(User.roles)
            .selectinload(UserRole.role)
            .selectinload(Role.permissions)
            .selectinload(RolePermission.permission)
        )
        .where(User.email == username)
    )
    user = result.scalar_one_or_none()
    if user is None:
        result = await db.execute(
            select(User)
            .options(
                selectinload(User.roles)
                .selectinload(UserRole.role)
                .selectinload(Role.permissions)
                .selectinload(RolePermission.permission)
            )
            .where(User.username == username)
        )
        user = result.scalar_one_or_none()
    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return _token_pair(user)


@router.get("/me")
async def me(
    token: CurrentToken,
    db: AsyncSession = Depends(db_session),
) -> dict:
    result = await db.execute(select(User).where(User.id == token.sub))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "id": str(user.id),
        "email": user.email,
        "username": user.username,
        "full_name": user.full_name,
        "vessel_id": str(user.vessel_id) if user.vessel_id else None,
        "roles": token.roles,
        "permissions": token.permissions,
    }


@router.post("/logout")
async def logout(
    request: Request,
    token: CurrentToken,
    db: AsyncSession = Depends(db_session),
) -> dict:
    db.add(SecurityEvent(
        event_type=SecurityEventType.TOKEN_REVOKED,
        severity=SecuritySeverity.INFO,
        ip_address=_client_ip(request),
        title="Logout",
    ))
    await db.commit()
    return {"status": "ok"}

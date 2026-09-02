"""
Auth routes — login, refresh, me, logout.

The login endpoint simulates the IPSec/SSL VPN handshake by recording
the connection fingerprint and emitting a SecurityEvent. Failed attempts
are counted by the IDS layer; once an IP crosses the brute-force threshold,
subsequent attempts return 429 until the window expires.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
    form: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(db_session),
) -> dict:
    """OAuth2 password flow — returns a JWT pair.

    Body (form): username, password. Username may be email or username.
    """
    ip = _client_ip(request)
    user_agent = request.headers.get("user-agent", "")

    if check_brute_force(ip):
        db.add(SecurityEvent(
            event_type=SecurityEventType.BRUTE_FORCE_DETECTED,
            severity=SecuritySeverity.HIGH,
            ip_address=ip,
            user_agent=user_agent,
            title="Brute force suspected",
            description="Repeated failed logins from same IP",
            payload={"path": str(request.url.path)},
        ))
        await db.commit()
        raise HTTPException(status_code=429, detail="Too many failed attempts, try later")

    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(User)
        .where(User.email == form.username)
        .options(
            selectinload(User.roles).selectinload(UserRole.role).selectinload(Role.permissions).selectinload(RolePermission.permission)
        )
    )
    user = result.scalar_one_or_none()
    if not user:
        result = await db.execute(
            select(User)
            .where(User.username == form.username)
            .options(
                selectinload(User.roles).selectinload(UserRole.role).selectinload(Role.permissions).selectinload(RolePermission.permission)
            )
        )
        user = result.scalar_one_or_none()

    if not user or not verify_password(form.password, user.hashed_password):
        record_login_failure(ip)
        db.add(SecurityEvent(
            event_type=SecurityEventType.LOGIN_FAILURE,
            severity=SecuritySeverity.MEDIUM,
            ip_address=ip,
            user_agent=user_agent,
            title="Login failure",
            description="Invalid credentials",
        ))
        await db.commit()
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if user.status != UserStatus.ACTIVE or user.is_deleted:
        raise HTTPException(status_code=403, detail="Account not active")

    user.last_login_at = datetime.now(timezone.utc)
    user.last_login_ip = ip
    user.failed_login_attempts = 0
    db.add(SecurityEvent(
        event_type=SecurityEventType.LOGIN_SUCCESS,
        severity=SecuritySeverity.INFO,
        user_id=user.id,
        ip_address=ip,
        user_agent=user_agent,
        title="Login success",
    ))
    await db.commit()

    tokens = _token_pair(user)
    # Pull roles + permissions for the user block
    roles_list = []
    perms_list: set[str] = set()
    for ur in user.roles:
        if ur.role:
            roles_list.append(ur.role.name)
            for rp in ur.role.permissions:
                if rp.permission:
                    perms_list.add(
                        f"{rp.permission.resource}:{rp.permission.action}:{rp.permission.scope}"
                    )
    return {
        **tokens,
        "user": {
            "id": str(user.id),
            "email": user.email,
            "username": user.username,
            "full_name": user.full_name,
            "vessel_id": str(user.vessel_id) if user.vessel_id else None,
            "roles": roles_list,
            "permissions": sorted(perms_list),
        },
    }


@router.post("/refresh")
async def refresh(
    request: Request,
    db: AsyncSession = Depends(db_session),
) -> dict:
    body = await request.json()
    token = body.get("refresh_token")
    if not token:
        raise HTTPException(status_code=400, detail="Missing refresh_token")
    try:
        payload = decode_token(token)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid token type")

    result = await db.execute(select(User).where(User.id == payload["sub"]))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not active")
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

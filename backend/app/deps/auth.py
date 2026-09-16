"""
FastAPI dependencies for auth, RBAC, and database sessions.
"""
from __future__ import annotations

from typing import Annotated, AsyncGenerator, Callable
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import TokenData, decode_token
from app.db.session import get_db, get_read_db
from app.models.user import User

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/auth/login", auto_error=False
)


async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with get_db() as s:
        yield s


async def read_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with get_read_db() as s:
        yield s


DBSession = Annotated[AsyncSession, Depends(db_session)]
ReadDBSession = Annotated[AsyncSession, Depends(read_db_session)]


async def get_current_token(
    request: Request,
    token: Annotated[str | None, Depends(oauth2_scheme)],
) -> TokenData:
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_token(token)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        ) from e
    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
        )
    return TokenData.from_payload(payload)


CurrentToken = Annotated[TokenData, Depends(get_current_token)]


async def get_current_user(
    db: AsyncSession = Depends(db_session),
    token: Annotated[str | None, Depends(oauth2_scheme)] = Depends(oauth2_scheme),
) -> User:
    """Get the current authenticated user from the JWT token."""
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_token(token)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        ) from e
    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
        )
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing subject in token",
        )
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    return user


UserInDependency = Annotated[User, Depends(get_current_user)]


def require_permission(resource: str, action: str, scope: str = "own") -> Callable:
    """Dependency factory that enforces a (resource, action, scope) permission."""

    async def _checker(token: CurrentToken) -> TokenData:
        # token.has_permission takes a single "resource:action:scope" string
        # (the JWT carries permissions in that flat form). We allow matching
        # at any broader scope: own < vessel < fleet < global.
        scope_order = ["own", "vessel", "fleet", "global"]
        target = scope_order.index(scope)
        for s in scope_order[target:]:
            if token.has_permission(f"{resource}:{action}:{s}"):
                return token
        # Fallback: any role-level override
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing permission: {resource}:{action}:{scope}",
        )

    return _checker


def require_role(*role_names: str) -> Callable:
    async def _checker(token: CurrentToken) -> TokenData:
        if not token.has_any_role(list(role_names)):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of roles: {', '.join(role_names)}",
            )
        return token

    return _checker


# ─── Vessel-scope helpers ──────────────────────────────────────────────
# `require_permission` answers "can the caller do this action at all".
# `assert_vessel_access` answers "is the resource in the caller's scope".
# Together they enforce both: role-level permission AND row-level
# vessel scoping. A purchasing officer on vessel 0 gets 404 on RFQs
# belonging to vessel 1, 2, 3, 4 — not 403, so we don't leak the
# existence of resources on other vessels.


def has_vessel_access(token: CurrentToken, vessel_id: UUID | None) -> bool:
    """True if the caller may access resources belonging to ``vessel_id``.

    Rules:
      * super_admin / fleet_admin: always True (cross-vessel by design).
      * Any other user with vessel_id == None (e.g. external suppliers
        or users with no vessel assignment): False. They must not get
        access to vessel-scoped resources.
      * Otherwise: True iff the caller's vessel_id matches.
    """
    if token.has_any_role(["super_admin", "fleet_admin"]):
        return True
    if token.vessel_id is None:
        return False
    if vessel_id is None:
        # Caller has a vessel; the resource has no vessel — deny.
        return False
    return str(token.vessel_id) == str(vessel_id)


async def assert_vessel_access(
    token: CurrentToken, vessel_id: UUID | None
) -> None:
    """Raise 404 (not 403) if the caller's vessel doesn't match.

    404 is intentional: it prevents an attacker from probing for
    the existence of resources on other vessels by watching for
    403 vs 404 differences.
    """
    if not has_vessel_access(token, vessel_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not found",
        )

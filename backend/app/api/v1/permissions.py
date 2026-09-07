"""
Permissions endpoints for the demo's `/permissions` page.

Two endpoints:

* ``GET /api/v1/permissions/me`` — open to any authenticated user.
  Returns the caller's id, roles, vessel_id, and the flat list of
  permission strings currently in their JWT. The page uses this for
  the "Your permissions" section that everyone sees.

* ``GET /api/v1/permissions/matrix`` — admin only. Returns the full
  role × permission matrix: every role from ``SYSTEM_ROLES`` and
  every permission from ``SYSTEM_PERMISSIONS``, plus a
  ``role_permissions`` map of which permissions are actually granted
  to each role in the DB. The page renders this as the green-check
  governance grid (admin-only view).

The matrix endpoint is admin-only because it exposes the *complete*
RBAC shape of the system. Non-admins don't need to know the global
matrix — they only need their own view (``/me``). The endpoint is
gated behind ``has_any_role(["super_admin", "fleet_admin"])`` and
returns 403 otherwise (not 404 — the existence of the role
hierarchy is not a secret; a fleet admin who tries to view the
full matrix just gets a 403).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps.auth import CurrentToken, DBSession
from app.models.user import (
    Permission,
    Role,
    RolePermission,
    SYSTEM_PERMISSIONS,
    SYSTEM_ROLES,
)

router = APIRouter()


@router.get("/me")
async def my_permissions(token: CurrentToken) -> dict:
    """Return the caller's own identity + permissions for the
    ``/permissions`` page.

    No DB reads — the JWT is the source of truth. This is also why
    the endpoint is fast: the page can call it on every render.

    A user with no roles or permissions gets an empty list, not a
    403. The page just renders "You have no permissions assigned"
    in that case. ``/me`` is intentionally open to all
    authenticated users — it only returns the caller's own info,
    which they already have via the JWT.
    """
    return {
        "user": {
            "sub": token.sub,
            "roles": token.roles,
            "vessel_id": str(token.vessel_id) if token.vessel_id else None,
        },
        "permissions": sorted(token.permissions),
    }


@router.get("/matrix")
async def permissions_matrix(
    db: DBSession,
    token: CurrentToken,
) -> dict:
    """Return the full role × permission matrix for the admin view.

    Three things in the response:

    * ``roles`` — every role from ``SYSTEM_ROLES`` (name, description,
      priority, is_system). The static list, not a DB read, so the
      endpoint stays consistent with the canonical definitions even
      if the seed was edited.
    * ``permissions`` — every permission from ``SYSTEM_PERMISSIONS``,
      broken out into ``resource``, ``action``, ``scope`` (and the
      flat ``"resource:action:scope"`` name). The page uses this to
      render the column headers.
    * ``role_permissions`` — a map of ``{role_name: [permission_name,
      ...]}`` reflecting the **actual DB grants** (i.e. the rows in
      ``role_permissions``). This is what the page renders as
      green/red checks.

    Super_admin is granted every permission in the seed, so its
    column will be all green. Other roles get their curated subset.
    """
    if not token.has_any_role(["super_admin", "fleet_admin"]):
        # 403, not 404: the endpoint exists, just not for non-admins.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin only",
        )

    # Pull the role-permission grants from the DB. The role list
    # itself comes from the static SYSTEM_ROLES (it never changes
    # at runtime), but the grants reflect the live state.
    rows = (
        await db.execute(
            select(Role.name, Permission.name)
            .join(RolePermission, RolePermission.role_id == Role.id)
            .join(Permission, Permission.id == RolePermission.permission_id)
        )
    ).all()
    role_permissions: dict[str, list[str]] = {}
    for role_name, perm_name in rows:
        role_permissions.setdefault(role_name, []).append(perm_name)
    # Sort for stable JSON output (helps the page diff-check).
    for role_name in role_permissions:
        role_permissions[role_name].sort()

    return {
        "roles": [
            {
                "name": r["name"],
                "description": r["description"],
                "priority": r["priority"],
                "is_system": r["is_system"],
            }
            for r in SYSTEM_ROLES
        ],
        "permissions": [
            {
                "name": f"{res}:{act}:{sc}",
                "resource": res,
                "action": act,
                "scope": sc,
            }
            for res, act, sc in SYSTEM_PERMISSIONS
        ],
        "role_permissions": role_permissions,
    }


__all__ = ["router"]

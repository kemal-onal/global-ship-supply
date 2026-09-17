"""API v1 router."""
from fastapi import APIRouter

from app.api.v1 import (
    auth,
    catalog,
    catering,
    clarification,
    customs,
    dashboard,
    marketplace,
    marketplace_simple,
    notifications,
    orders,
    permissions,
    ports,
    rfq,
    supplier_portal,
    sync,
    users,
    vessels,
)
from app.api.v1.internal import internal_router

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(clarification.router, tags=["marketplace"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(vessels.router, prefix="/vessels", tags=["vessels"])
api_router.include_router(ports.router, prefix="/ports", tags=["ports"])
api_router.include_router(catalog.router, prefix="/catalog", tags=["catalog"])
api_router.include_router(orders.router, prefix="/orders", tags=["orders"])
api_router.include_router(rfq.router, prefix="/rfq", tags=["rfq"])
api_router.include_router(catering.router, prefix="/catering", tags=["catering"])
api_router.include_router(customs.router, prefix="/customs", tags=["customs"])
api_router.include_router(sync.router, prefix="/sync", tags=["sync"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
api_router.include_router(permissions.router, prefix="/permissions", tags=["permissions"])
# Marketplace redesign (migration 0005). Routes live at the top
# level of /api/v1/orders/... so the OpenAPI tags match the
# purchaser's mental model of "things I do with an order".
# clarification.router is included BEFORE orders.router because both
# routers expose paths under /orders/ — FastAPI matches in include
# order, so putting clarification first prevents it from being
# shadowed and resolves GET /api/v1/orders/{id}/clarification.
# Marketplace redesign routes (redesigned flow with proposal, compose, etc.)
api_router.include_router(marketplace.router, tags=["marketplace"])
# Simplified marketplace (new flow)
api_router.include_router(marketplace_simple.router, tags=["marketplace-simple"])
# Supplier portal: the supplier-facing app, separate prefix
# because it has its own auth model (supplier users, not
# vessel-scoped). Kept as a sibling of the marketplace routers.
api_router.include_router(supplier_portal.router, tags=["supplier-portal"])
api_router.include_router(internal_router, prefix="/internal", tags=["internal"])
# Co-Authored-By: Claude Code <noreply@anthropic.com>
# 🤖 Generated with [Claude Code](https://claude.com/claude-code)

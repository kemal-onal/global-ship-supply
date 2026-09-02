"""API v1 router."""
from fastapi import APIRouter

from app.api.v1 import (
    auth,
    catalog,
    catering,
    customs,
    dashboard,
    notifications,
    orders,
    ports,
    rfq,
    sync,
    users,
    vessels,
)
from app.api.v1.internal import internal_router

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
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
api_router.include_router(internal_router, prefix="/internal", tags=["internal"])

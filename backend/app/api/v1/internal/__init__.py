"""Internal API routers (sim ingestion, admin tools, etc.).

Unlike the public API, these endpoints are not protected by user JWT.
They are intended to be reachable only on the loopback interface
(``127.0.0.1``) or within a private Docker network.

Add a new internal router by:

1. Creating ``app/api/v1/internal/<feature>.py`` with a ``router``
   exported.
2. Importing it below and including it.
"""
from fastapi import APIRouter

from app.api.v1.internal import ais

internal_router = APIRouter()
internal_router.include_router(ais.router, prefix="/ais", tags=["internal-ais"])

__all__ = ["internal_router"]

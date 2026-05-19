"""v1 API surface aggregator.

Combines every v1 sub-router into a single `APIRouter` that the top-level
API aggregator mounts under the configured v1 prefix. Add new v1
sub-routers here so versioning stays explicit and contained.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.routers.arbitration import router as arbitration_router
from app.api.v1.routers.auth import router as auth_router
from app.api.v1.routers.coordination import router as coordination_router
from app.api.v1.routers.governance import router as governance_router
from app.api.v1.routers.health import router as health_router

api_router_v1 = APIRouter()
api_router_v1.include_router(health_router)
api_router_v1.include_router(auth_router, prefix="/auth")
api_router_v1.include_router(governance_router, prefix="/governance")
api_router_v1.include_router(coordination_router, prefix="/coordination")
api_router_v1.include_router(arbitration_router, prefix="/arbitration")

__all__ = ["api_router_v1"]

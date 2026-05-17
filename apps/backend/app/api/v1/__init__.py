"""v1 API surface aggregator.

Combines every v1 sub-router into a single `APIRouter` that the top-level
API aggregator mounts under the configured v1 prefix. Add new v1
sub-routers here so versioning stays explicit and contained.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.routers.health import router as health_router

api_router_v1 = APIRouter()
api_router_v1.include_router(health_router)

__all__ = ["api_router_v1"]

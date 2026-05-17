"""Top-level API aggregator.

Mounts every versioned API surface (`v1`, future `v2`, ...) onto a single
`APIRouter` that `main.py` attaches to the FastAPI app. Versions are kept
isolated under their own prefixes so we can evolve them independently.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import api_router_v1
from app.core.config import Settings, get_settings


def build_api_router(settings: Settings | None = None) -> APIRouter:
    """Construct the aggregated API router using configured prefixes."""

    settings = settings or get_settings()
    router = APIRouter()
    router.include_router(api_router_v1, prefix=settings.API_V1_PREFIX)
    return router


__all__ = ["build_api_router"]

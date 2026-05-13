"""Health endpoints — v1 transport layer.

Three orthogonal probes:

* `GET /health` — overall health snapshot (dashboards / smoke checks).
* `GET /live`   — liveness probe (process is up and responsive).
* `GET /ready`  — readiness probe (dependencies wired; safe for traffic).

This module is intentionally thin: it composes a `HealthService` from
DI, calls one of three async methods, and maps the domain report to the
versioned response schema. Orchestration, timeout policy, and
aggregation semantics live entirely inside `HealthService`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from redis.asyncio import Redis

from app.api.v1.schemas.health import HealthResponse
from app.core.config import Settings, get_settings
from app.core.redis import get_redis
from app.db.session import AsyncSessionLocal
from app.services.health_service import HealthService

router = APIRouter(tags=["health"])


def get_health_service(
    settings: Settings = Depends(get_settings),
    redis: Redis = Depends(get_redis),
) -> HealthService:
    """FastAPI dependency factory for `HealthService`.

    Co-located with the router so the FastAPI-specific wiring stays out
    of the service module. Each request constructs a fresh service
    instance — services are cheap and stateless.
    """
    return HealthService(
        settings=settings,
        session_factory=AsyncSessionLocal,
        redis=redis,
    )


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Service health",
    description="High-level health snapshot including app metadata.",
)
async def health(
    service: HealthService = Depends(get_health_service),
) -> HealthResponse:
    report = await service.health()
    return HealthResponse.from_report(report)


@router.get(
    "/live",
    response_model=HealthResponse,
    summary="Liveness probe",
    description="Returns 200 as long as the process can serve requests.",
)
async def live(
    service: HealthService = Depends(get_health_service),
) -> HealthResponse:
    report = await service.liveness()
    return HealthResponse.from_report(report)


@router.get(
    "/ready",
    response_model=HealthResponse,
    summary="Readiness probe",
    description=(
        "Returns 200 when PostgreSQL and Redis are reachable. Returns 503 "
        "if any dependency check fails so orchestrators stop routing "
        "traffic to this replica."
    ),
)
async def ready(
    response: Response,
    service: HealthService = Depends(get_health_service),
) -> HealthResponse:
    report = await service.readiness()
    if report.status != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse.from_report(report)

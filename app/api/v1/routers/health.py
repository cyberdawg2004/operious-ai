"""Health endpoints — v1 transport layer.

Three orthogonal probes:

* `GET /health` — overall health snapshot (dashboards / smoke checks).
* `GET /live`   — liveness probe (process is up and responsive).
* `GET /ready`  — readiness probe (dependencies wired; safe for traffic).

Pure transport: each handler validates inputs, awaits a single service
call, and maps the domain report to the versioned response schema.
Service construction is centralised under `app.dependencies.services`;
this module never builds a service.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status

from app.api.v1.schemas.health import HealthResponse
from app.dependencies.services import get_health_service
from app.services.health_service import HealthService

router = APIRouter(tags=["health"])


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

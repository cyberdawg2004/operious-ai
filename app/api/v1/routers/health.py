"""Operational health endpoints for the v1 API.

Three orthogonal probes:

* `/health` – overall service health (use for dashboards / smoke checks)
* `/live`   – liveness probe (process is up and not deadlocked)
* `/ready`  – readiness probe (dependencies wired; safe to receive traffic)

`/ready` actively pings PostgreSQL and Redis; `/health` and `/live` stay
dependency-free so they can never be brought down by downstream issues.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field
from redis.asyncio import Redis

from app.core.config import Settings, get_settings
from app.core.health import (
    DependencyCheck,
    aggregate_status,
    check_database,
    check_redis,
)
from app.core.redis import get_redis
from app.db.session import AsyncSessionLocal

router = APIRouter(tags=["health"])

CheckName = Literal["health", "live", "ready"]
ProbeStatus = Literal["ok", "degraded", "unavailable"]


class DependencyResult(BaseModel):
    name: str
    status: Literal["ok", "unavailable"]
    latency_ms: float
    error: str | None = None


class HealthResponse(BaseModel):
    """Stable JSON contract for all health probes."""

    status: ProbeStatus = Field(..., description="Aggregated probe status.")
    check: CheckName = Field(..., description="Which probe produced this response.")
    app: str = Field(..., description="Service name.")
    version: str = Field(..., description="Service version.")
    environment: str = Field(..., description="Runtime environment.")
    timestamp: datetime = Field(..., description="UTC timestamp of the check.")
    dependencies: list[DependencyResult] = Field(
        default_factory=list,
        description="Per-dependency results (populated for /ready).",
    )


def _envelope(
    check: CheckName,
    settings: Settings,
    status_value: ProbeStatus = "ok",
    dependencies: list[DependencyCheck] | None = None,
) -> HealthResponse:
    return HealthResponse(
        status=status_value,
        check=check,
        app=settings.APP_NAME,
        version=settings.APP_VERSION,
        environment=settings.ENVIRONMENT,
        timestamp=datetime.now(timezone.utc),
        dependencies=[
            DependencyResult(
                name=d.name, status=d.status, latency_ms=d.latency_ms, error=d.error
            )
            for d in (dependencies or [])
        ],
    )


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Service health",
    description="High-level health snapshot including app metadata.",
)
async def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    return _envelope("health", settings)


@router.get(
    "/live",
    response_model=HealthResponse,
    summary="Liveness probe",
    description="Returns 200 as long as the process can serve requests.",
)
async def live(settings: Settings = Depends(get_settings)) -> HealthResponse:
    return _envelope("live", settings)


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
    settings: Settings = Depends(get_settings),
    redis: Redis = Depends(get_redis),
) -> HealthResponse:
    checks: list[DependencyCheck] = [
        await check_database(AsyncSessionLocal),
        await check_redis(redis),
    ]
    overall = aggregate_status(checks)
    if overall != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return _envelope("ready", settings, overall, checks)

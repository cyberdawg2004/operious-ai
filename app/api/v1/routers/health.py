"""Operational health endpoints for the v1 API.

Three orthogonal probes:

* `/health` – overall service health (use for dashboards / smoke checks)
* `/live`   – liveness probe (process is up and not deadlocked)
* `/ready`  – readiness probe (dependencies wired; safe to receive traffic)

Right now `/ready` is dependency-free, but the signature is shaped so we
can plug DB, cache, and AI-provider checks in later without changing the
public contract.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.config import Settings, get_settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Stable JSON contract for all health probes."""

    status: Literal["ok", "degraded", "unavailable"] = Field(
        ..., description="Aggregated probe status."
    )
    check: Literal["health", "live", "ready"] = Field(
        ..., description="Which probe produced this response."
    )
    app: str = Field(..., description="Service name.")
    version: str = Field(..., description="Service version.")
    environment: str = Field(..., description="Runtime environment.")
    timestamp: datetime = Field(..., description="UTC timestamp of the check.")


def _build_response(
    check: Literal["health", "live", "ready"],
    settings: Settings,
    status: Literal["ok", "degraded", "unavailable"] = "ok",
) -> HealthResponse:
    return HealthResponse(
        status=status,
        check=check,
        app=settings.APP_NAME,
        version=settings.APP_VERSION,
        environment=settings.ENVIRONMENT,
        timestamp=datetime.now(timezone.utc),
    )


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Service health",
    description="High-level health snapshot including app metadata.",
)
async def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    return _build_response("health", settings)


@router.get(
    "/live",
    response_model=HealthResponse,
    summary="Liveness probe",
    description="Returns 200 as long as the process can serve requests.",
)
async def live(settings: Settings = Depends(get_settings)) -> HealthResponse:
    return _build_response("live", settings)


@router.get(
    "/ready",
    response_model=HealthResponse,
    summary="Readiness probe",
    description=(
        "Returns 200 when the service is ready to accept traffic. "
        "Downstream dependency checks (DB, cache, AI providers) will be "
        "wired in here as they come online."
    ),
)
async def ready(settings: Settings = Depends(get_settings)) -> HealthResponse:
    return _build_response("ready", settings)

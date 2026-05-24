"""Transport contracts for the v1 health endpoints.

Pure Pydantic schemas. They define the JSON wire format and nothing
else:

* No imports from `app.db.*` — schemas never carry ORM types.
* No imports from `app.services.*` — schemas never depend on
  orchestration.
* Conversion FROM domain objects happens via explicit `from_report`
  classmethods so the mapping is a single, reviewable surface.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.queue_admission import QueueDepthReport
from app.services.health_service import DependencyReport, HealthReport

CheckName = Literal["health", "live", "ready"]
ProbeStatus = Literal["ok", "degraded", "unavailable"]
DependencyStatus = Literal["ok", "unavailable"]
QueueStatus = Literal["ok", "degraded", "saturated", "unavailable"]


class DependencyResultSchema(BaseModel):
    """Per-dependency entry in the readiness response."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(..., description="Dependency identifier (e.g. 'postgres').")
    status: DependencyStatus = Field(..., description="Probe outcome.")
    latency_ms: float = Field(..., description="Probe latency in milliseconds.")
    error: str | None = Field(None, description="Exception class name on failure.")

    @classmethod
    def from_domain(cls, dep: DependencyReport) -> "DependencyResultSchema":
        return cls(
            name=dep.name,
            status=dep.status,
            latency_ms=dep.latency_ms,
            error=dep.error,
        )


class QueueDepthSchema(BaseModel):
    """Per-Celery-queue pressure entry in the health response."""

    model_config = ConfigDict(frozen=True)

    depth: int = Field(..., description="Current Redis queue depth.")
    limit: int = Field(..., description="Configured queue depth admission limit.")
    status: QueueStatus = Field(..., description="Queue pressure status.")
    queue_name: str | None = Field(None, description="Physical Redis queue name.")
    error: str | None = Field(None, description="Exception class name on failure.")

    @classmethod
    def from_domain(cls, queue: QueueDepthReport) -> "QueueDepthSchema":
        return cls(
            depth=queue.depth,
            limit=queue.limit,
            status=queue.status,
            queue_name=queue.queue_name,
            error=queue.error,
        )


def _empty_dependencies() -> list[DependencyResultSchema]:
    return []


def _empty_queues() -> dict[str, QueueDepthSchema]:
    return {}


class HealthResponse(BaseModel):
    """Stable JSON contract for `/health`, `/live`, and `/ready`."""

    model_config = ConfigDict(frozen=True)

    status: ProbeStatus = Field(..., description="Aggregated probe status.")
    check: CheckName = Field(..., description="Which probe produced this response.")
    app: str = Field(..., description="Service name.")
    version: str = Field(..., description="Service version.")
    environment: str = Field(..., description="Runtime environment.")
    timestamp: datetime = Field(..., description="UTC timestamp of the check.")
    dependencies: list[DependencyResultSchema] = Field(
        default_factory=_empty_dependencies,
        description="Per-dependency results (populated for /ready).",
    )
    queues: dict[str, QueueDepthSchema] = Field(
        default_factory=_empty_queues,
        description="Per-Celery-queue depth reports.",
    )

    @classmethod
    def from_report(cls, report: HealthReport) -> "HealthResponse":
        return cls(
            status=report.status,
            check=report.check,
            app=report.app,
            version=report.version,
            environment=report.environment,
            timestamp=report.timestamp,
            dependencies=[
                DependencyResultSchema.from_domain(d) for d in report.dependencies
            ],
            queues={
                name: QueueDepthSchema.from_domain(queue)
                for name, queue in report.queues.items()
            },
        )


__all__ = [
    "CheckName",
    "ProbeStatus",
    "DependencyStatus",
    "QueueStatus",
    "DependencyResultSchema",
    "QueueDepthSchema",
    "HealthResponse",
]

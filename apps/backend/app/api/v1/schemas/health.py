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
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.core.queue_admission import QueueDepthReport

CheckName = Literal["health", "live", "ready"]
ProbeStatus = Literal["ok", "degraded", "unavailable"]
DependencyStatus = Literal["ok", "unavailable"]
QueueStatus = Literal["ok", "warn", "critical", "unknown"]
AdmissionPressure = Literal["ok", "warn", "critical"]


class DependencyReportLike(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def status(self) -> DependencyStatus: ...

    @property
    def latency_ms(self) -> float: ...

    @property
    def error(self) -> str | None: ...


class AdmissionPressureReportLike(Protocol):
    @property
    def redis_memory_pct(self) -> float | None: ...

    @property
    def pressure(self) -> AdmissionPressure: ...


class HealthReportLike(Protocol):
    @property
    def status(self) -> ProbeStatus: ...

    @property
    def check(self) -> CheckName: ...

    @property
    def app(self) -> str: ...

    @property
    def version(self) -> str: ...

    @property
    def environment(self) -> str: ...

    @property
    def timestamp(self) -> datetime: ...

    @property
    def dependencies(self) -> tuple[DependencyReportLike, ...]: ...

    @property
    def queues(self) -> dict[str, QueueDepthReport]: ...

    @property
    def admission(self) -> AdmissionPressureReportLike | None: ...


class DependencyResultSchema(BaseModel):
    """Per-dependency entry in the readiness response."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(..., description="Dependency identifier (e.g. 'postgres').")
    status: DependencyStatus = Field(..., description="Probe outcome.")
    latency_ms: float = Field(..., description="Probe latency in milliseconds.")
    error: str | None = Field(None, description="Exception class name on failure.")

    @classmethod
    def from_domain(cls, dep: DependencyReportLike) -> "DependencyResultSchema":
        return cls(
            name=dep.name,
            status=dep.status,
            latency_ms=dep.latency_ms,
            error=dep.error,
        )


class QueueDepthSchema(BaseModel):
    """Per-Celery-queue pressure entry in the health response."""

    model_config = ConfigDict(frozen=True)

    depth: int = Field(..., description="Current broker queue depth.")
    limit: int = Field(..., description="Configured queue depth admission limit.")
    status: QueueStatus = Field(..., description="Queue pressure status.")
    queue_name: str | None = Field(None, description="Physical broker queue name.")
    age_seconds: float | None = Field(
        None,
        description="Oldest message age in seconds when available.",
    )
    error: str | None = Field(None, description="Exception class name on failure.")
    messages_ready: int | None = Field(
        None,
        description="RabbitMQ ready message count when available.",
    )
    messages_unacknowledged: int | None = Field(
        None,
        description="RabbitMQ unacknowledged message count when available.",
    )
    messages: int | None = Field(
        None,
        description="RabbitMQ total message count when available.",
    )

    @classmethod
    def from_domain(cls, queue: QueueDepthReport) -> "QueueDepthSchema":
        return cls(
            depth=queue.depth,
            limit=queue.limit,
            status=queue.status,
            queue_name=queue.queue_name,
            age_seconds=queue.age_seconds,
            error=queue.error,
            messages_ready=queue.messages_ready,
            messages_unacknowledged=queue.messages_unacknowledged,
            messages=queue.messages,
        )


class AdmissionPressureSchema(BaseModel):
    """Admission pressure summary for capacity-aware health checks."""

    model_config = ConfigDict(frozen=True)

    redis_memory_pct: float | None = Field(
        None,
        description="Redis used memory percentage, when maxmemory is set.",
    )
    pressure: AdmissionPressure = Field(..., description="Admission pressure.")

    @classmethod
    def from_domain(
        cls,
        admission: AdmissionPressureReportLike,
    ) -> "AdmissionPressureSchema":
        return cls(
            redis_memory_pct=admission.redis_memory_pct,
            pressure=admission.pressure,
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
    admission: AdmissionPressureSchema | None = Field(
        None,
        description="Read-only admission pressure snapshot.",
    )

    @classmethod
    def from_report(cls, report: HealthReportLike) -> "HealthResponse":
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
            admission=(
                AdmissionPressureSchema.from_domain(report.admission)
                if report.admission is not None
                else None
            ),
        )


__all__ = [
    "CheckName",
    "ProbeStatus",
    "DependencyStatus",
    "AdmissionPressure",
    "AdmissionPressureSchema",
    "QueueStatus",
    "DependencyResultSchema",
    "QueueDepthSchema",
    "HealthResponse",
]

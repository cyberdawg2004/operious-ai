"""Typed admission-control decisions."""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass
from datetime import datetime


class AdmissionOutcome(str, enum.Enum):
    """Admission outcome for an inbound workload."""

    ADMIT = "ADMIT"
    DEFER = "DEFER"
    REJECT = "REJECT"


class AdmissionReason(str, enum.Enum):
    """Machine-readable pressure reason for non-ADMIT decisions."""

    QUEUE_DEPTH_EXCEEDED = "QUEUE_DEPTH_EXCEEDED"
    QUEUE_AGE_EXCEEDED = "QUEUE_AGE_EXCEEDED"
    REDIS_MEMORY_PRESSURE = "REDIS_MEMORY_PRESSURE"
    DB_POOL_PRESSURE = "DB_POOL_PRESSURE"
    TENANT_QUOTA_EXCEEDED = "TENANT_QUOTA_EXCEEDED"
    TELEMETRY_UNAVAILABLE_REALTIME = "telemetry_unavailable_realtime"
    TELEMETRY_UNAVAILABLE_VOICE = "telemetry_unavailable_voice"


class AdmissionChannelClass(str, enum.Enum):
    """Risk class used when admission telemetry is unavailable.

    Async ticket channels may fail open because queued work can recover
    later. Voice is realtime and fails closed when capacity telemetry is
    unavailable because overflow becomes customer-facing silence.
    """

    ASYNC_TICKET = "async_ticket"
    BATCH = "batch"
    REALTIME_CHAT = "realtime_chat"
    VOICE = "voice"
    INTERNAL_EXECUTION = "internal_execution"


@dataclass(frozen=True, slots=True)
class AdmissionDecision:
    """In-memory result of an AdmissionGate evaluation."""

    decision_id: uuid.UUID
    outcome: AdmissionOutcome
    reason: AdmissionReason | None
    queue_name: str
    queue_depth: int
    queue_age_seconds: float | None
    redis_memory_pct: float | None
    db_pool_wait_ms: float | None
    retry_after_seconds: int
    evaluated_at: datetime
    queue_depth_available: bool = True
    queue_age_available: bool = True
    redis_memory_available: bool = True
    unavailable_reasons: tuple[str, ...] = ()
    channel_class: AdmissionChannelClass = AdmissionChannelClass.ASYNC_TICKET

    @property
    def telemetry_unavailable(self) -> bool:
        """Whether any required admission telemetry could not be read."""

        return (
            not self.queue_depth_available
            or not self.queue_age_available
            or not self.redis_memory_available
            or bool(self.unavailable_reasons)
        )

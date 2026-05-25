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

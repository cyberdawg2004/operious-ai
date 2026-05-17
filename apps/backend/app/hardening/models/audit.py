"""`HardeningAudit` — apex immutable audit record."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.hardening.enums import (
    HardeningStatus,
    HardeningTraceKind,
)
from app.hardening.identity import HardeningAuditId
from app.hardening.models.finding import HardeningFinding


@dataclass(frozen=True, slots=True)
class HardeningAudit:
    """One immutable hardening-audit record.

    An audit is the apex container for findings produced by ONE
    runtime call. It is write-once and replay-safe.
    """

    audit_id: HardeningAuditId
    seed: str
    kind: HardeningTraceKind
    status: HardeningStatus
    findings: tuple[HardeningFinding, ...]
    started_at: datetime
    ended_at: datetime
    summary: str | None = None
    correlation_id: str | None = None
    tenant_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.seed:
            raise ValueError(
                "HardeningAudit.seed must be non-empty"
            )
        if self.started_at.tzinfo is None:
            raise ValueError(
                "HardeningAudit.started_at must be tz-aware"
            )
        if self.ended_at.tzinfo is None:
            raise ValueError(
                "HardeningAudit.ended_at must be tz-aware"
            )
        if self.ended_at < self.started_at:
            raise ValueError(
                "HardeningAudit.ended_at must be >= started_at"
            )
        prev_ordinal = -1
        for finding in self.findings:
            if finding.ordinal <= prev_ordinal:
                raise ValueError(
                    "HardeningAudit.findings must be strictly "
                    "monotonic by ordinal"
                )
            prev_ordinal = finding.ordinal

    @property
    def is_clean(self) -> bool:
        return not self.findings

    @property
    def has_critical_findings(self) -> bool:
        return any(
            f.severity.value == "critical" for f in self.findings
        )


__all__ = ["HardeningAudit"]

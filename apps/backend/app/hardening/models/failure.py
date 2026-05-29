"""Failure-containment record.

The substrate **classifies** failures. It does not handle them.
A `FailureContainmentRecord` is the audit-safe shape produced by
`HardeningRuntime.record_failure()` — it carries enough lineage
to reconstruct what happened without enabling autonomous
recovery.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.hardening.enums import (
    ContainmentClassification,
    FailureClassification,
    HardeningSeverity,
    SubstrateName,
)
from app.hardening.identity import (
    FailureContainmentRecordId,
)


@dataclass(frozen=True, slots=True)
class FailureContainmentRecord:
    """One immutable failure-containment record.

    Attributes:
        record_id:                Stable id.
        substrate:                Substrate that experienced the
                                   failure.
        classification:           Bounded failure classification.
        containment:              Whether the failure was
                                   contained inside its semantic
                                   boundary.
        severity:                 Bounded severity.
        summary:                  Short human-readable summary.
        recorded_at:              UTC timestamp.
        error_class_name:         Free-form error-class string.
        evidence:                 Sorted, deduplicated evidence
                                   handles.
        correlation_id:           Optional correlation handle.
        tenant_id:                Optional tenant scope.
        attributes:               Canonical metadata payload.
    """

    record_id: FailureContainmentRecordId
    substrate: SubstrateName
    classification: FailureClassification
    containment: ContainmentClassification
    severity: HardeningSeverity
    summary: str
    recorded_at: datetime
    error_class_name: str
    evidence: tuple[str, ...] = ()
    correlation_id: str | None = None
    tenant_id: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict[str, Any])

    def __post_init__(self) -> None:
        if not self.summary:
            raise ValueError(
                "FailureContainmentRecord.summary must be non-empty"
            )
        if not self.error_class_name:
            raise ValueError(
                "FailureContainmentRecord.error_class_name must be "
                "non-empty"
            )
        if self.recorded_at.tzinfo is None:
            raise ValueError(
                "FailureContainmentRecord.recorded_at must be "
                "tz-aware"
            )


__all__ = ["FailureContainmentRecord"]

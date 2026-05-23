"""Query model + paginated result for the persistence repository."""

from __future__ import annotations

from dataclasses import dataclass

from app.arbitration.enums import ArbitrationOutcome
from app.arbitration.identity import (
    ArbitrationCaseId,
    ArbitrationEvaluationId,
)
from app.arbitration.persistence.records import ArbitrationRecord


@dataclass(frozen=True, slots=True)
class ArbitrationQuery:
    """Filter parameters for `ArbitrationPersistenceProtocol.list_records`.

    Multiple filters AND together. ``None`` means "no constraint".
    """

    case_id: ArbitrationCaseId | None = None
    evaluation_id: ArbitrationEvaluationId | None = None
    outcome: ArbitrationOutcome | None = None
    correlation_id: str | None = None
    request_id: str | None = None
    tenant_id: str | None = None
    limit: int | None = None
    offset: int = 0


@dataclass(frozen=True, slots=True)
class RecordPage:
    """Paginated repository response (deterministically ordered)."""

    records: tuple[ArbitrationRecord, ...]
    total: int
    limit: int = 0
    offset: int = 0


__all__ = ["ArbitrationQuery", "RecordPage"]

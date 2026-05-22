"""QA persistence query/page value objects."""

from __future__ import annotations

from dataclasses import dataclass

from app.qa.persistence.records import QAScoreRecord


@dataclass(frozen=True, slots=True)
class QAScoreQuery:
    score_id: str | None = None
    inspection_id: str | None = None
    execution_id: str | None = None
    tenant_id: str | None = None
    supervisor_decision_kind: str | None = None
    limit: int = 100
    offset: int = 0

    def __post_init__(self) -> None:
        if self.limit < 1:
            raise ValueError("QAScoreQuery.limit must be >= 1")
        if self.offset < 0:
            raise ValueError("QAScoreQuery.offset must be >= 0")


@dataclass(frozen=True, slots=True)
class QAScorePage:
    items: tuple[QAScoreRecord, ...]
    total: int
    offset: int = 0


__all__ = ["QAScorePage", "QAScoreQuery"]

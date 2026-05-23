"""SOP intelligence persistence query and page models."""

from __future__ import annotations

from dataclasses import dataclass

from app.sop_intelligence.persistence.records import ApprovalRecord


@dataclass(frozen=True, slots=True)
class ApprovalQuery:
    approval_id: str | None = None
    tenant_id: str | None = None
    document_id: str | None = None
    status: str | None = None
    min_confidence: float | None = None
    limit: int = 100
    offset: int = 0

    def __post_init__(self) -> None:
        if self.limit < 1:
            raise ValueError("ApprovalQuery.limit must be >= 1")
        if self.offset < 0:
            raise ValueError("ApprovalQuery.offset must be >= 0")


@dataclass(frozen=True, slots=True)
class ApprovalPage:
    items: tuple[ApprovalRecord, ...] = ()
    total: int = 0
    limit: int = 0
    offset: int = 0


__all__ = [
    "ApprovalPage",
    "ApprovalQuery",
]

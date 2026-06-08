"""Query models for case approvals."""

from __future__ import annotations

from dataclasses import dataclass

from app.approvals.persistence.records import (
    CaseApprovalOutboxRecord,
    CaseApprovalRecord,
)


@dataclass(frozen=True, slots=True)
class CaseApprovalQuery:
    tenant_id: str | None = None
    session_id: str | None = None
    execution_id: str | None = None
    dispatch_id: str | None = None
    resolution_proposal_id: str | None = None
    status: str | None = None
    entry_category: str | None = None
    limit: int = 50
    offset: int = 0


@dataclass(frozen=True, slots=True)
class CaseApprovalPage:
    items: tuple[CaseApprovalRecord, ...]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True, slots=True)
class CaseApprovalOutboxQuery:
    tenant_id: str | None = None
    status: str | None = None
    dead_letter: bool | None = None
    limit: int = 100
    offset: int = 0


@dataclass(frozen=True, slots=True)
class CaseApprovalOutboxPage:
    items: tuple[CaseApprovalOutboxRecord, ...]
    total: int
    limit: int
    offset: int


__all__ = [
    "CaseApprovalOutboxPage",
    "CaseApprovalOutboxQuery",
    "CaseApprovalPage",
    "CaseApprovalQuery",
]

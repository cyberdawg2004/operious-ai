"""Resolution proposal persistence query/page models."""

from __future__ import annotations

from dataclasses import dataclass

from app.resolution.persistence.records import (
    ResolutionOutboundDraftRecord,
    ResolutionProposalRecord,
)


@dataclass(frozen=True, slots=True)
class ResolutionProposalQuery:
    proposal_id: str | None = None
    tenant_id: str | None = None
    session_id: str | None = None
    execution_id: str | None = None
    dispatch_id: str | None = None
    status: str | None = None
    limit: int = 100
    offset: int = 0

    def __post_init__(self) -> None:
        if self.limit < 1:
            raise ValueError("ResolutionProposalQuery.limit must be >= 1")
        if self.offset < 0:
            raise ValueError("ResolutionProposalQuery.offset must be >= 0")


@dataclass(frozen=True, slots=True)
class ResolutionProposalPage:
    items: tuple[ResolutionProposalRecord, ...] = ()
    total: int = 0
    limit: int = 0
    offset: int = 0


@dataclass(frozen=True, slots=True)
class ResolutionOutboundDraftQuery:
    draft_id: str | None = None
    tenant_id: str | None = None
    proposal_id: str | None = None
    session_id: str | None = None
    execution_id: str | None = None
    dispatch_id: str | None = None
    status: str | None = None
    limit: int = 100
    offset: int = 0

    def __post_init__(self) -> None:
        if self.limit < 1:
            raise ValueError("ResolutionOutboundDraftQuery.limit must be >= 1")
        if self.offset < 0:
            raise ValueError("ResolutionOutboundDraftQuery.offset must be >= 0")


@dataclass(frozen=True, slots=True)
class ResolutionOutboundDraftPage:
    items: tuple[ResolutionOutboundDraftRecord, ...] = ()
    total: int = 0
    limit: int = 0
    offset: int = 0


__all__ = [
    "ResolutionOutboundDraftPage",
    "ResolutionOutboundDraftQuery",
    "ResolutionProposalPage",
    "ResolutionProposalQuery",
]

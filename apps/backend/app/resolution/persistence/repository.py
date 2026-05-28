"""Storage contract for resolution proposals."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.resolution.persistence.models import (
    ResolutionOutboundDraftPage,
    ResolutionOutboundDraftQuery,
    ResolutionProposalPage,
    ResolutionProposalQuery,
)
from app.resolution.persistence.records import (
    ResolutionOutboundDraftRecord,
    ResolutionProposalRecord,
)


@runtime_checkable
class ResolutionProposalPersistenceProtocol(Protocol):
    """Tenant-scoped resolution proposal persistence."""

    async def create_resolution_proposal(
        self,
        record: ResolutionProposalRecord,
        *,
        expected_tenant_id: str,
    ) -> ResolutionProposalRecord: ...

    async def get_resolution_proposal(
        self,
        proposal_id: str,
        *,
        expected_tenant_id: str,
    ) -> ResolutionProposalRecord | None: ...

    async def list_resolution_proposals(
        self,
        query: ResolutionProposalQuery,
        *,
        expected_tenant_id: str,
    ) -> ResolutionProposalPage: ...


@runtime_checkable
class ResolutionOutboundDraftPersistenceProtocol(Protocol):
    """Tenant-scoped outbound draft persistence."""

    async def create_resolution_outbound_draft(
        self,
        record: ResolutionOutboundDraftRecord,
        *,
        expected_tenant_id: str,
    ) -> ResolutionOutboundDraftRecord: ...

    async def get_resolution_outbound_draft(
        self,
        draft_id: str,
        *,
        expected_tenant_id: str,
    ) -> ResolutionOutboundDraftRecord | None: ...

    async def list_resolution_outbound_drafts(
        self,
        query: ResolutionOutboundDraftQuery,
        *,
        expected_tenant_id: str,
    ) -> ResolutionOutboundDraftPage: ...


__all__ = [
    "ResolutionOutboundDraftPersistenceProtocol",
    "ResolutionProposalPersistenceProtocol",
]

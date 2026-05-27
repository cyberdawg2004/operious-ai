"""Storage contract for resolution proposals."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.resolution.persistence.models import (
    ResolutionProposalPage,
    ResolutionProposalQuery,
)
from app.resolution.persistence.records import ResolutionProposalRecord


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


__all__ = ["ResolutionProposalPersistenceProtocol"]

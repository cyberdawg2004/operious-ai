"""Storage contract for resolution proposals."""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

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
from app.resolution.enums import (
    ResolutionOutboundDraftStatus,
    ResolutionProposalStatus,
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

    async def update_resolution_proposal_status(
        self,
        proposal_id: str,
        *,
        expected_tenant_id: str,
        status: ResolutionProposalStatus,
        governance_decision_id: UUID | None = None,
    ) -> ResolutionProposalRecord: ...

    async def update_resolution_proposal_reply(
        self,
        proposal_id: str,
        *,
        expected_tenant_id: str,
        proposed_customer_reply: str,
        governance_decision_id: UUID | None = None,
    ) -> ResolutionProposalRecord:
        """Replace the customer-facing reply text for a proposal.

        Used when an approved SME recommendation supersedes the agent's
        original proposed reply. Callers MUST ground-validate the new
        reply before invoking this method.
        """
        ...


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

    async def update_resolution_outbound_draft_status_for_proposal(
        self,
        proposal_id: str,
        *,
        expected_tenant_id: str,
        status: ResolutionOutboundDraftStatus,
        governance_decision_id: UUID | None = None,
    ) -> ResolutionOutboundDraftRecord | None: ...

    async def update_resolution_outbound_draft_body_for_proposal(
        self,
        proposal_id: str,
        *,
        expected_tenant_id: str,
        draft_body: str,
        draft_body_sha256: str,
        governance_decision_id: UUID | None = None,
    ) -> ResolutionOutboundDraftRecord | None:
        """Replace the no-send draft body for a proposal's draft.

        Mirrors :meth:`update_resolution_proposal_reply` so an approved
        SME recommendation also supersedes the outbound draft text.
        """
        ...


__all__ = [
    "ResolutionOutboundDraftPersistenceProtocol",
    "ResolutionProposalPersistenceProtocol",
]

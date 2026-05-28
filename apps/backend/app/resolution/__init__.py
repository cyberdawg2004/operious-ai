"""Autonomous resolution proposal substrate."""

from app.resolution.enums import (
    ResolutionAutonomyDecision,
    ResolutionGovernanceVerdict,
    ResolutionOutboundDraftStatus,
    ResolutionProposalStatus,
    ResolutionSupervisorVerdict,
)
from app.resolution.identity import (
    ResolutionOutboundDraftId,
    ResolutionProposalId,
    as_resolution_outbound_draft_id,
    as_resolution_proposal_id,
    derive_resolution_outbound_draft_id,
    derive_resolution_proposal_id,
)
from app.resolution.persistence import (
    InMemoryResolutionProposalPersistence,
    PostgresResolutionProposalPersistence,
    ResolutionOutboundDraftPage,
    ResolutionOutboundDraftPersistenceProtocol,
    ResolutionOutboundDraftQuery,
    ResolutionOutboundDraftRecord,
    ResolutionProposalPage,
    ResolutionProposalPersistenceProtocol,
    ResolutionProposalQuery,
    ResolutionProposalRecord,
)

__all__ = [
    "InMemoryResolutionProposalPersistence",
    "PostgresResolutionProposalPersistence",
    "ResolutionAutonomyDecision",
    "ResolutionGovernanceVerdict",
    "ResolutionOutboundDraftId",
    "ResolutionOutboundDraftPage",
    "ResolutionOutboundDraftPersistenceProtocol",
    "ResolutionOutboundDraftQuery",
    "ResolutionOutboundDraftRecord",
    "ResolutionOutboundDraftStatus",
    "ResolutionProposalId",
    "ResolutionProposalPage",
    "ResolutionProposalPersistenceProtocol",
    "ResolutionProposalQuery",
    "ResolutionProposalRecord",
    "ResolutionProposalStatus",
    "ResolutionSupervisorVerdict",
    "as_resolution_outbound_draft_id",
    "as_resolution_proposal_id",
    "derive_resolution_outbound_draft_id",
    "derive_resolution_proposal_id",
]

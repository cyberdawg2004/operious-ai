"""Autonomous resolution proposal substrate."""

from app.resolution.enums import (
    ResolutionAutonomyDecision,
    ResolutionGovernanceVerdict,
    ResolutionProposalStatus,
    ResolutionSupervisorVerdict,
)
from app.resolution.identity import (
    ResolutionProposalId,
    as_resolution_proposal_id,
    derive_resolution_proposal_id,
)
from app.resolution.persistence import (
    InMemoryResolutionProposalPersistence,
    PostgresResolutionProposalPersistence,
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
    "ResolutionProposalId",
    "ResolutionProposalPage",
    "ResolutionProposalPersistenceProtocol",
    "ResolutionProposalQuery",
    "ResolutionProposalRecord",
    "ResolutionProposalStatus",
    "ResolutionSupervisorVerdict",
    "as_resolution_proposal_id",
    "derive_resolution_proposal_id",
]

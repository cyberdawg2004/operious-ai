"""SOP Intelligence Agent public surface.

The substrate observes persisted operational evidence and writes only
pending approval proposals. It never applies proposal content to tenant
knowledge documents.
"""

from app.sop_intelligence.enums import ApprovalStatus
from app.sop_intelligence.exceptions import (
    SOPIntelligenceEligibilityError,
    SOPIntelligenceError,
    SOPIntelligenceNotFoundError,
    SOPIntelligencePersistenceError,
)
from app.sop_intelligence.identity import (
    ApprovalEventId,
    ApprovalId,
    as_approval_id,
    derive_approval_event_id,
    derive_approval_id,
)
from app.sop_intelligence.persistence import (
    ApprovalPage,
    ApprovalQuery,
    ApprovalRecord,
    InMemorySOPApprovalPersistence,
    PostgresSOPApprovalPersistence,
    SOPApprovalPersistenceProtocol,
)
from app.sop_intelligence.runtime import SOPIntelligenceRuntime

__all__ = [
    "ApprovalId",
    "ApprovalEventId",
    "ApprovalPage",
    "ApprovalQuery",
    "ApprovalRecord",
    "ApprovalStatus",
    "InMemorySOPApprovalPersistence",
    "PostgresSOPApprovalPersistence",
    "SOPApprovalPersistenceProtocol",
    "SOPIntelligenceEligibilityError",
    "SOPIntelligenceError",
    "SOPIntelligenceNotFoundError",
    "SOPIntelligencePersistenceError",
    "SOPIntelligenceRuntime",
    "as_approval_id",
    "derive_approval_event_id",
    "derive_approval_id",
]

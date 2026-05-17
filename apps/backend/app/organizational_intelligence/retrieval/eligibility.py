"""Retrieval-eligibility derivation.

Eligibility is a **deterministic projection** of approval status.

The mapping is pure:

    APPROVED        →  ELIGIBLE
    UNDER_REVIEW    →  PENDING
    CANDIDATE       →  PENDING
    REJECTED        →  INELIGIBLE
    SUPERSEDED      →  INELIGIBLE
    RETIRED         →  RESTRICTED

The substrate **never** sets eligibility autonomously — every
public path that derives it does so through this module.
"""

from __future__ import annotations

from app.organizational_intelligence.enums import (
    MemoryArtifactStatus,
    RetrievalEligibility,
)
from app.organizational_intelligence.exceptions import (
    IntelligenceAuthorityError,
)


_STATUS_TO_ELIGIBILITY: dict[
    MemoryArtifactStatus, RetrievalEligibility
] = {
    MemoryArtifactStatus.APPROVED: RetrievalEligibility.ELIGIBLE,
    MemoryArtifactStatus.UNDER_REVIEW: RetrievalEligibility.PENDING,
    MemoryArtifactStatus.CANDIDATE: RetrievalEligibility.PENDING,
    MemoryArtifactStatus.REJECTED: RetrievalEligibility.INELIGIBLE,
    MemoryArtifactStatus.SUPERSEDED: RetrievalEligibility.INELIGIBLE,
    MemoryArtifactStatus.RETIRED: RetrievalEligibility.RESTRICTED,
}


def derive_eligibility(
    status: MemoryArtifactStatus,
) -> RetrievalEligibility:
    """Pure derivation of eligibility from approval status."""
    try:
        return _STATUS_TO_ELIGIBILITY[status]
    except KeyError as exc:  # pragma: no cover - defensive
        raise IntelligenceAuthorityError(
            f"no eligibility derivation for status {status!r}"
        ) from exc


def is_retrievable(eligibility: RetrievalEligibility) -> bool:
    return eligibility is RetrievalEligibility.ELIGIBLE


def require_eligible(eligibility: RetrievalEligibility) -> None:
    if not is_retrievable(eligibility):
        raise IntelligenceAuthorityError(
            f"artifact eligibility is {eligibility.value}; "
            f"retrieval requires ELIGIBLE"
        )


__all__ = [
    "derive_eligibility",
    "is_retrievable",
    "require_eligible",
]

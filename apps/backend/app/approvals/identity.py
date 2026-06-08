"""Deterministic identities for approval queue records."""

from __future__ import annotations

import uuid
from typing import NewType

from app.identity import project_optional_str


ApprovalCaseId = NewType("ApprovalCaseId", uuid.UUID)
ApprovalOutboxId = NewType("ApprovalOutboxId", uuid.UUID)
ApprovalOutboxClaimId = NewType("ApprovalOutboxClaimId", uuid.UUID)
SmeRecommendationId = NewType("SmeRecommendationId", uuid.UUID)

_APPROVAL_CASE_NAMESPACE = uuid.UUID("51b3132f-2f18-4e68-a002-ef97051b0001")
_APPROVAL_OUTBOX_NAMESPACE = uuid.UUID("51b3132f-2f18-4e68-a002-ef97051b0002")
_APPROVAL_OUTBOX_CLAIM_NAMESPACE = uuid.UUID(
    "51b3132f-2f18-4e68-a002-ef97051b0003"
)
_SME_RECOMMENDATION_NAMESPACE = uuid.UUID(
    "51b3132f-2f18-4e68-a002-ef97051b0004"
)


def derive_approval_dedup_key(
    *,
    tenant_id: str,
    execution_id: str | None,
    dispatch_id: str | None,
    session_id: str | None,
    entry_category: str,
) -> str:
    """Derive the stable idempotency key for producer ingress."""

    return str(
        uuid.uuid5(
            _APPROVAL_CASE_NAMESPACE,
            "|".join(
                (
                    tenant_id,
                    project_optional_str(execution_id),
                    project_optional_str(dispatch_id),
                    project_optional_str(session_id),
                    entry_category,
                )
            ),
        )
    )


def derive_approval_case_id(
    *,
    tenant_id: str,
    dedup_key: str,
) -> ApprovalCaseId:
    return ApprovalCaseId(
        uuid.uuid5(_APPROVAL_CASE_NAMESPACE, f"{tenant_id}|{dedup_key}")
    )


def derive_approval_outbox_id(
    *,
    approval_case_id: str,
) -> ApprovalOutboxId:
    return ApprovalOutboxId(
        uuid.uuid5(_APPROVAL_OUTBOX_NAMESPACE, approval_case_id)
    )


def derive_approval_outbox_claim_id(
    *,
    approval_case_id: str,
    publisher_id: str,
) -> ApprovalOutboxClaimId:
    return ApprovalOutboxClaimId(
        uuid.uuid5(
            _APPROVAL_OUTBOX_CLAIM_NAMESPACE,
            f"{approval_case_id}|{publisher_id}",
        )
    )


def derive_sme_recommendation_id(
    *,
    approval_case_id: str,
    guidance_round: int,
) -> SmeRecommendationId:
    return SmeRecommendationId(
        uuid.uuid5(
            _SME_RECOMMENDATION_NAMESPACE,
            f"{approval_case_id}|round:{guidance_round}",
        )
    )


__all__ = [
    "ApprovalCaseId",
    "ApprovalOutboxClaimId",
    "ApprovalOutboxId",
    "SmeRecommendationId",
    "derive_approval_case_id",
    "derive_approval_dedup_key",
    "derive_approval_outbox_claim_id",
    "derive_approval_outbox_id",
    "derive_sme_recommendation_id",
]

"""Regenerate a stuck case's cached SME recommendation against the fixed
GeneratedSmeReviewer (the "preserve an already-governed reply" fix).

Some cases entered SME review before app/sme/generated_reviewer.py was
fixed to preserve an already-governed proposal reply when there's no
operator guidance. Their case_approval_records.metadata["sme_recommendation"]
still holds the OLD, independently-(re)generated draft from before the
fix -- re-approving as-is would still hit that stale, possibly-ungrounded
draft. This re-runs SmeReviewRuntime.review_case() directly (bypassing
CaseApprovalService.review_case's PENDING_SME_REVIEW/GUIDANCE_IN_PROGRESS
status guard, since these cases are long past that status) to get a
fresh recommendation, and overwrites the stored metadata with it -- the
case's own status/resolved_at/resolved_by/etc. are left untouched.

For a case already APPROVED (its bound action fired historically, before
the dual-surface fix existed, so the action itself is not re-fired here),
also attempts delivery immediately via complete_reconciled_resolution,
since the stale metadata was the only thing blocking it. For a case still
AWAITING_APPROVAL, only the metadata is regenerated -- actually firing
the bound action is left to the normal human-approval flow, not this
script.

Dry-run by default; --apply to write.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, replace
from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.approvals.enums import CaseApprovalStatus
from app.approvals.exceptions import CaseApprovalNotFoundError
from app.approvals.persistence import PostgresCaseApprovalPersistence
from app.core.config import get_settings
from app.data_protection.crypto import DataProtectionService
from app.data_protection.kms import build_master_key_unwrap
from app.db.session import get_owner_session_factory
from app.governance.persistence import PostgresGovernanceRepository
from app.resolution.persistence import (
    PostgresResolutionProposalPersistence,
    ResolutionProposalRecord,
)
from app.approvals.persistence import CaseApprovalRecord
from app.runtime import ResolutionGovernanceGate, build_resolution_governance_runtime
from app.runtime.grounding import CitationCoverageGroundingChecker
from app.services.case_approval_service import CaseApprovalService
from app.sme import SmeCaseContext, build_sme_review_runtime
from app.tenant.persistence import PostgresTenantConfigurationRepository


@dataclass(frozen=True, slots=True)
class RegenerateResult:
    dry_run: bool
    approval_case_id: str
    old_recommended_reply: str | None
    new_recommended_reply: str | None
    delivered: bool


def _data_protection_service(session: AsyncSession) -> DataProtectionService | None:
    settings = get_settings()
    if (
        not settings.DATA_PROTECTION_MASTER_KEYS.strip()
        and not settings.TENANT_CREDENTIAL_MASTER_KEY.strip()
    ):
        return None
    return DataProtectionService.from_settings(
        session,
        settings,
        master_key_unwrap=build_master_key_unwrap(settings),
        legacy_credential_key=settings.TENANT_CREDENTIAL_MASTER_KEY,
    )


def _context_for_record(
    record: CaseApprovalRecord, *, proposal: ResolutionProposalRecord | None
) -> SmeCaseContext:
    # Mirrors app.services.case_approval_service._context_for_record
    # exactly -- same inputs the live review_case call would build.
    metadata = dict(record.metadata)
    if proposal is not None:
        metadata.setdefault("confidence", proposal.confidence)
    return SmeCaseContext(
        approval_case_id=record.approval_case_id,
        tenant_id=record.tenant_id,
        session_id=record.session_id,
        execution_id=record.execution_id,
        dispatch_id=record.dispatch_id,
        resolution_proposal_id=record.resolution_proposal_id,
        entry_category=record.entry_category.value,
        ticket_ref=record.ticket_ref,
        product=record.product,
        issue_summary=record.issue_summary
        or (proposal.resolution_category if proposal is not None else None),
        proposed_customer_reply=(
            proposal.proposed_customer_reply if proposal is not None else None
        ),
        recommended_actions=(
            tuple(proposal.recommended_actions) if proposal is not None else ()
        ),
        citations=tuple(proposal.evidence) if proposal is not None else (),
        metadata=metadata,
    )


def _build_case_approval_service(session: AsyncSession) -> CaseApprovalService:
    data_protection = _data_protection_service(session)
    governance_repository = PostgresGovernanceRepository(session)
    return CaseApprovalService(
        persistence=PostgresCaseApprovalPersistence(
            session, data_protection=data_protection
        ),
        sme_runtime=build_sme_review_runtime(),
        resolution_repository=PostgresResolutionProposalPersistence(
            session, data_protection=data_protection
        ),
        governance_repository=governance_repository,
        resolution_governance_gate=ResolutionGovernanceGate(
            governance_runtime=build_resolution_governance_runtime(
                persistence=governance_repository,
                grounding_checker=CitationCoverageGroundingChecker(
                    document_repository=PostgresTenantConfigurationRepository(
                        session, data_protection=data_protection
                    ),
                ),
            )
        ),
        session=session,
    )


async def regenerate_stale_sme_recommendation(
    *,
    session: AsyncSession,
    approval_case_id: str,
    tenant_id: str,
    apply: bool = False,
) -> RegenerateResult:
    data_protection = _data_protection_service(session)
    service = _build_case_approval_service(session)
    persistence = PostgresCaseApprovalPersistence(
        session, data_protection=data_protection
    )
    resolutions = PostgresResolutionProposalPersistence(
        session, data_protection=data_protection
    )
    sme_runtime = build_sme_review_runtime()
    record = await persistence.get_case(
        approval_case_id, expected_tenant_id=tenant_id
    )
    if record is None:
        raise CaseApprovalNotFoundError(
            f"unknown approval case: {approval_case_id}"
        )
    proposal = (
        await resolutions.get_resolution_proposal(
            record.resolution_proposal_id, expected_tenant_id=tenant_id
        )
        if record.resolution_proposal_id is not None
        else None
    )
    old_recommendation = record.metadata.get("sme_recommendation")
    old_reply = (
        old_recommendation.get("recommended_reply")
        if isinstance(old_recommendation, dict)
        else None
    )

    fresh_recommendation = await sme_runtime.review_case(
        _context_for_record(record, proposal=proposal),
        guidance=None,
        guidance_round=record.guidance_round,
    )

    if not apply:
        return RegenerateResult(
            dry_run=True,
            approval_case_id=approval_case_id,
            old_recommended_reply=old_reply,
            new_recommended_reply=fresh_recommendation.recommended_reply,
            delivered=False,
        )

    updated_record = replace(
        record,
        sme_recommendation_id=fresh_recommendation.recommendation_id,
        metadata={
            **dict(record.metadata),
            "sme_recommendation": fresh_recommendation.to_dict(),
        },
    )
    await persistence.update_case(updated_record, expected_tenant_id=tenant_id)
    await session.commit()

    delivered = False
    if record.status is CaseApprovalStatus.APPROVED:
        delivered = await service.complete_reconciled_resolution(
            approval_case_id=approval_case_id,
            tenant_id=tenant_id,
            resolved_by=record.resolved_by or "unknown",
            note=record.resolution_note,
        )
        if delivered:
            await session.commit()
        else:
            await session.rollback()

    return RegenerateResult(
        dry_run=False,
        approval_case_id=approval_case_id,
        old_recommended_reply=old_reply,
        new_recommended_reply=fresh_recommendation.recommended_reply,
        delivered=delivered,
    )


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--tenant-id", default="anker-pilot")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="actually write the regenerated metadata (and deliver if approved)",
    )
    return parser.parse_args(argv)


async def _amain(argv: Sequence[str] | None = None) -> RegenerateResult:
    args = _parse_args(argv)
    session_factory = get_owner_session_factory()
    async with session_factory() as session:
        result = await regenerate_stale_sme_recommendation(
            session=session,
            approval_case_id=args.case_id,
            tenant_id=args.tenant_id,
            apply=args.apply,
        )
        print(
            {
                "dry_run": result.dry_run,
                "approval_case_id": result.approval_case_id,
                "old_recommended_reply": result.old_recommended_reply,
                "new_recommended_reply": result.new_recommended_reply,
                "delivered": result.delivered,
            }
        )
        return result


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()

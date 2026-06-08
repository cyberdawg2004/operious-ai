#!/usr/bin/env python3
"""Seed a REAL SME-reviewed approval case directly against the database.

This is NOT a mock. It drives the exact production code path the runtime
producers use:

    ApprovalQueueIngressService.request_case_review(...)   # real ingress
    CaseApprovalService.review_case(...)                   # real SME reviewer

against a real DB session with tenant RLS context installed (same mechanism
the Celery workers use). The result is a genuine ``awaiting_approval`` case
that the Command Center case-approval queue lists and can approve / guide /
escalate.

It creates a ``coordination_human_review`` case, which does not depend on a
pre-existing resolution proposal or seeded knowledge — so it is deterministic
and runnable on any environment that has a database. For a *resolution-backed*
case (where approve delivers a grounded customer reply), use the full HTTP
seeder ``seed_anker_demo.py`` with the ``warranty-replacement-require-approval``
ticket, which seeds Anker knowledge and lets the real pipeline produce a
grounded ``PENDING_HUMAN_APPROVAL`` proposal.

Usage (from repo root, backend venv, with DATABASE_URL set):

    python -m apps.backend.scripts.anker_demo.seed_approval_case \
        --tenant-id anker-pilot --count 1

Then open the Command Center → Case Approvals (requires a token with
``tenant.approvals.read``; approve/guide require ``tenant.actions.approve`` /
``tenant.resolution.guide``).
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from typing import Any

from app.approvals.enums import CaseApprovalEntryCategory, CaseApprovalStatus
from app.approvals.ingress import (
    ApprovalQueueIngressService,
    CaseApprovalReviewRequest,
)
from app.approvals.persistence import PostgresCaseApprovalPersistence
from app.core.config import get_settings
from app.data_protection.crypto import DataProtectionService
from app.db.session import get_session_factory
from app.db.tenant_context import set_current_tenant
from app.governance.persistence import PostgresGovernanceRepository
from app.resolution.persistence import PostgresResolutionProposalPersistence
from app.runtime.conversation_generation import (
    GroundedConversationGenerationRuntime,
)
from app.services.case_approval_service import CaseApprovalService
from app.sme import GeneratedSmeReviewer, SmeReviewRuntime


def _data_protection(session: Any) -> DataProtectionService | None:
    settings = get_settings()
    if (
        not settings.DATA_PROTECTION_MASTER_KEYS.strip()
        and not settings.TENANT_CREDENTIAL_MASTER_KEY.strip()
    ):
        return None
    return DataProtectionService.from_settings(session, settings)


def _sme_runtime() -> SmeReviewRuntime:
    # Real reviewer: governed grounded generation. With no Anthropic key it
    # uses the same grounded citation-coverage fallback the resolution runtime
    # uses — not a stub. (A coordination case has no retrieved evidence, so the
    # reviewer honestly flags citation_review_required.)
    return SmeReviewRuntime(
        llm_reviewer=GeneratedSmeReviewer(
            generation_runtime=GroundedConversationGenerationRuntime(
                llm_client=None,
            ),
        ),
    )


async def _seed_one(*, tenant_id: str, index: int) -> dict[str, str]:
    session_id = str(uuid.uuid4())
    execution_id = str(uuid.uuid4())
    dispatch_id = str(uuid.uuid4())

    set_current_tenant(tenant_id)
    try:
        session_factory = get_session_factory()
        async with session_factory() as session:
            data_protection = _data_protection(session)
            persistence = PostgresCaseApprovalPersistence(
                session, data_protection=data_protection
            )
            ingress = ApprovalQueueIngressService(persistence=persistence)
            service = CaseApprovalService(
                persistence=persistence,
                sme_runtime=_sme_runtime(),
                resolution_repository=PostgresResolutionProposalPersistence(
                    session, data_protection=data_protection
                ),
                governance_repository=PostgresGovernanceRepository(session),
                session=session,
            )

            created = await ingress.request_case_review(
                CaseApprovalReviewRequest(
                    tenant_id=tenant_id,
                    session_id=session_id,
                    execution_id=execution_id,
                    dispatch_id=dispatch_id,
                    entry_category=CaseApprovalEntryCategory.COORDINATION_HUMAN_REVIEW,
                    ticket_ref=f"demo-seed-{index}",
                    product="Anker PowerCore 26800",
                    issue_summary=(
                        "Coordination policy requested human review of a "
                        "warranty-replacement coordination outcome."
                    ),
                    metadata={
                        "source": "seed_approval_case",
                        "demo": True,
                        "coordination_policy_escalated": True,
                    },
                ),
                expected_tenant_id=tenant_id,
            )
            if created.status is CaseApprovalStatus.PENDING_SME_REVIEW:
                created = await service.review_case(
                    approval_case_id=created.approval_case_id,
                    tenant_id=tenant_id,
                )
            await session.commit()
            return {
                "approval_case_id": created.approval_case_id,
                "tenant_id": created.tenant_id,
                "status": created.status.value,
                "sme_recommendation_id": created.sme_recommendation_id or "",
            }
    finally:
        set_current_tenant(None)


async def _main_async(*, tenant_id: str, count: int) -> None:
    for index in range(count):
        result = await _seed_one(tenant_id=tenant_id, index=index)
        print(
            f"[seed] case {index + 1}/{count}: "
            f"approval_case_id={result['approval_case_id']} "
            f"status={result['status']} tenant={result['tenant_id']}"
        )
    print(
        "[seed] done. Open Command Center -> Case Approvals "
        "(token needs tenant.approvals.read)."
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed a real SME-reviewed approval case via the production "
        "ingress + reviewer."
    )
    parser.add_argument("--tenant-id", default="anker-pilot")
    parser.add_argument("--count", type=int, default=1)
    args = parser.parse_args()
    asyncio.run(_main_async(tenant_id=args.tenant_id, count=max(1, args.count)))


if __name__ == "__main__":
    main()

"""SME approval worker tasks."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from threading import Thread
from typing import Any, TypeVar

from app.approvals.enums import CaseApprovalEntryCategory
from app.approvals.persistence import PostgresCaseApprovalPersistence
from app.cognition.llm_factory import build_llm_client
from app.core.config import get_settings
from app.data_protection.crypto import DataProtectionService
from app.data_protection.kms import build_master_key_unwrap
from app.db.session import get_session_factory
from app.db.tenant_context import set_current_tenant
from app.governance.persistence import PostgresGovernanceRepository
from app.queues import QUEUE_SME_APPROVAL
from app.resolution.persistence import PostgresResolutionProposalPersistence
from app.services.case_approval_service import CaseApprovalService
from app.sme import build_sme_review_runtime
from app.workers.celery_app import celery_app
from app.workers.queue_admission import clear_worker_queue_age

logger = logging.getLogger(__name__)

_T = TypeVar("_T")


@celery_app.task(  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator]
    name="review_case_approval",
    queue=QUEUE_SME_APPROVAL,
    bind=True,
    ignore_result=True,
    max_retries=2,
    default_retry_delay=30,
)
def review_case_approval(
    _self: Any,
    approval_case_id: str,
    tenant_id: str,
    _enqueued_at: str | None = None,
) -> dict[str, object]:
    """Run SME review for one approval case."""
    del _enqueued_at

    set_current_tenant(tenant_id)
    try:
        return _run_async(
            review_case_approval_runtime(
                approval_case_id=approval_case_id,
                tenant_id=tenant_id,
            ),
            tenant_id=tenant_id,
        )
    finally:
        set_current_tenant(None)


async def review_case_approval_runtime(
    *,
    approval_case_id: str,
    tenant_id: str,
) -> dict[str, object]:
    set_current_tenant(tenant_id)
    try:
        await clear_worker_queue_age(
            queue_name=QUEUE_SME_APPROVAL,
            member_id=approval_case_id,
        )
        session_factory = get_session_factory()
        async with session_factory() as session:
            data_protection = _data_protection_service(session)
            approval_persistence = PostgresCaseApprovalPersistence(
                session,
                data_protection=data_protection,
            )
            resolution_repo = PostgresResolutionProposalPersistence(
                session,
                data_protection=data_protection,
            )
            tenant_config_repo = _build_tenant_config_repo(session)

            # MVP-SME: enrich the approval case with SMECasePackage before
            # the human reviewer opens it. Fail-open: any failure leaves
            # the case intact and review proceeds without the package.
            if tenant_config_repo is not None:
                await _enrich_with_sme_case_package(
                    approval_case_id=approval_case_id,
                    tenant_id=tenant_id,
                    approval_persistence=approval_persistence,
                    resolution_repo=resolution_repo,
                    tenant_config_repo=tenant_config_repo,
                    session=session,
                )

            service = CaseApprovalService(
                persistence=approval_persistence,
                sme_runtime=build_sme_review_runtime(),
                resolution_repository=resolution_repo,
                governance_repository=PostgresGovernanceRepository(session),
                session=session,
            )
            record = await service.review_case(
                approval_case_id=approval_case_id,
                tenant_id=tenant_id,
            )
            await session.commit()
            return {
                "status": "completed",
                "approval_case_id": record.approval_case_id,
                "tenant_id": record.tenant_id,
                "queue_status": record.status.value,
                "sme_recommendation_id": record.sme_recommendation_id,
            }
    finally:
        set_current_tenant(None)


async def _enrich_with_sme_case_package(
    *,
    approval_case_id: str,
    tenant_id: str,
    approval_persistence: Any,
    resolution_repo: Any,
    tenant_config_repo: Any,
    session: Any,
) -> None:
    """Run SMEReviewerAgent and store the case package on the approval record.

    Fail-open: any failure logs a warning and returns without modifying the
    approval case. The human reviewer proceeds with whatever context they have.
    """
    from dataclasses import replace
    from app.agents.governed.base import AgentInput
    from app.agents.governed.proposal import AgentProposalStatus
    from app.agents.governed.sme_reviewer import SMEReviewerAgent
    try:
        settings = get_settings()
        # Load the approval case.
        approval_case = await approval_persistence.get_case(
            approval_case_id,
            expected_tenant_id=tenant_id,
        )
        if approval_case is None:
            return

        # Only run on fraud/escalation cases — these need the most context.
        sme_categories = {
            CaseApprovalEntryCategory.FRAUD_RISK_HIGH,
            CaseApprovalEntryCategory.RESOLUTION_REQUIRE_APPROVAL,
            CaseApprovalEntryCategory.RESOLUTION_NEEDS_HUMAN_APPROVAL,
        }
        if approval_case.entry_category not in sme_categories:
            return

        # Load the associated resolution proposal for reply + citations.
        proposal = None
        if approval_case.resolution_proposal_id:
            proposal = await resolution_repo.get_resolution_proposal(
                approval_case.resolution_proposal_id,
                expected_tenant_id=tenant_id,
            )

        ticket_text = approval_case.issue_summary or ""
        proposed_reply = ""
        citations: list[dict[str, Any]] = []
        lineage_events: list[dict[str, Any]] = []
        fraud_signal = None
        extracted_fields: dict[str, Any] = {}

        if proposal is not None:
            proposed_reply = proposal.proposed_customer_reply or ""
            citations = [dict(ev) for ev in proposal.evidence]
            # Surface fraud signal if present in gate reasons
            from app.resolution.persistence.records import resolution_proposal_gate_reasons
            proposal_gate_reasons = resolution_proposal_gate_reasons(proposal)
            if "fraud_risk_high" in proposal_gate_reasons or "fraud_risk" in proposal_gate_reasons:
                fraud_signal = {
                    "gate_reasons": list(proposal.gate_reasons),
                    "governance_verdict": proposal.governance_verdict.value,
                }
            lineage_events = [
                {
                    "act": "resolution_proposal",
                    "substrate": "execution",
                    "timestamp": proposal.created_at.isoformat(),
                    "note": f"status={proposal.status.value} verdict={proposal.governance_verdict.value}",
                }
            ]

        llm_client = build_llm_client(settings, prefer_reasoning_model=True)
        agent = SMEReviewerAgent(
            llm_client=llm_client,
            tenant_configuration_repository=tenant_config_repo,
        )
        agent_input = AgentInput(
            tenant_id=tenant_id,
            session_id=str(approval_case.session_id or approval_case_id),
            execution_id=str(approval_case.execution_id or approval_case_id),
            content={
                "case_id": approval_case_id,
                "ticket_text": ticket_text,
                "proposed_reply": proposed_reply,
                "fraud_signal": fraud_signal,
                "citations": citations,
                "lineage_events": lineage_events,
                "extracted_fields": extracted_fields,
                "entry_category": approval_case.entry_category.value,
                "recommended_actions": [],
            },
        )
        agent_proposal = await agent.run(agent_input)

        if (
            agent_proposal.status == AgentProposalStatus.COMPLETED
            and agent_proposal.output is not None
        ):
            # Store the SME case package in the approval case metadata.
            existing_metadata = dict(approval_case.metadata)
            existing_metadata["sme_case_package"] = dict(agent_proposal.output)
            enriched = replace(approval_case, metadata=existing_metadata)
            await approval_persistence.update_case(
                enriched,
                expected_tenant_id=tenant_id,
            )
            logger.info(
                "sme_case_package_stored approval_case_id=%s tenant=%s",
                approval_case_id, tenant_id,
            )
        else:
            logger.warning(
                "sme_case_package_skipped approval_case_id=%s tenant=%s status=%s reason=%s",
                approval_case_id, tenant_id,
                agent_proposal.status.value, agent_proposal.reason,
            )
    except Exception:
        logger.warning(
            "sme_case_package_enrichment_failed approval_case_id=%s tenant=%s",
            approval_case_id, tenant_id,
            exc_info=True,
        )


def _build_tenant_config_repo(session: Any) -> Any:
    """Build tenant config repository from the current session."""
    try:
        from app.tenant.persistence import PostgresTenantConfigurationRepository
        return PostgresTenantConfigurationRepository(session)
    except Exception:
        return None


def _data_protection_service(session: Any) -> DataProtectionService | None:
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


def _run_async(coro: Coroutine[Any, Any, _T], *, tenant_id: str) -> _T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        set_current_tenant(tenant_id)
        try:
            return asyncio.run(coro)
        finally:
            set_current_tenant(None)

    results: list[_T] = []
    errors: list[BaseException] = []

    def _runner() -> None:
        set_current_tenant(tenant_id)
        try:
            results.append(asyncio.run(coro))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            set_current_tenant(None)

    thread = Thread(target=_runner)
    thread.start()
    thread.join()
    if errors:
        raise errors[0]
    if not results:
        raise RuntimeError("approval review coroutine returned no result")
    return results[0]


__all__ = ["review_case_approval", "review_case_approval_runtime"]

"""MVP-5 — QA→Trainer→KB loop worker tasks.

The aggregate_qa_signals task:
1. Reads QAScoreRecords for ALL tenants (or a single tenant) over the
   configured rolling window.
2. Runs QASignalAggregator to identify categories below the grounding threshold.
3. For each weak category, loads representative KB documents and runs
   KBTrainerAgent to generate a KBImprovementProposal.
4. Routes the proposal to the KB admin review queue via
   TenantConfigurationRuntime.create_knowledge_document() with an approved
   ApprovalRecord (system-generated for trainer proposals).
5. MVP-4's contradiction check fires automatically on the submitted document.

Fail-closed: any per-category failure is logged and skipped — the task
continues to other categories and completes. A single bad proposal cannot
block the rest.

INVARIANT: The trainer NEVER writes directly to the active KB. Every
proposal enters as QUARANTINED + PENDING_INDEX and requires human
approval + contradiction check before becoming APPROVED/ACTIVE.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Coroutine
from datetime import datetime, timezone
from threading import Thread
from typing import Any, TypeVar

from app.agents.governed.base import AgentInput
from app.agents.governed.kb_trainer import KBTrainerAgent
from app.agents.governed.proposal import AgentProposalStatus
from app.cognition.llm_factory import build_llm_client
from app.core.config import get_settings
from app.db.session import get_session_factory
from app.db.tenant_context import set_current_tenant
from app.qa.aggregator import QASignalAggregator, WeakCategory
from app.qa.persistence import PostgresQAPersistence
from app.queues import QUEUE_TRAINER
from app.tenant.enums import TenantKnowledgeDocumentType, TenantKnowledgeDocumentStatus
from app.tenant.persistence import PostgresTenantConfigurationRepository
from app.tenant.persistence.models import TenantKnowledgeDocumentQuery
from app.tenant.runtime import TenantConfigurationRuntime
from app.workers.celery_app import celery_app
from app.workers.queue_admission import clear_worker_queue_age

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

# Trainer system identity — the "proposed_by" field on approval records
# created by the trainer agent. Clearly marks them as AI-generated proposals
# awaiting human review.
_TRAINER_PRINCIPAL_ID = "agent:kb_trainer"

# Document type for trainer-proposed KB improvements
_TRAINER_DOCUMENT_TYPE = TenantKnowledgeDocumentType.SOP


@celery_app.task(  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator]
    name="aggregate_qa_signals",
    queue=QUEUE_TRAINER,
    bind=True,
    ignore_result=True,
    max_retries=1,
    default_retry_delay=60,
)
def aggregate_qa_signals(
    _self: Any,
    tenant_id: str,
    _enqueued_at: str | None = None,
) -> dict[str, object]:
    """Aggregate QA signals for one tenant and submit KB improvement proposals."""
    del _enqueued_at

    set_current_tenant(tenant_id)
    try:
        return _run_async(
            aggregate_qa_signals_runtime(tenant_id=tenant_id),
            tenant_id=tenant_id,
        )
    finally:
        set_current_tenant(None)


async def aggregate_qa_signals_runtime(
    *,
    tenant_id: str,
) -> dict[str, object]:
    """Core async logic for the QA signal aggregation and KB proposal pipeline."""
    set_current_tenant(tenant_id)
    try:
        settings = get_settings()
        await clear_worker_queue_age(
            queue_name=QUEUE_TRAINER,
            member_id=tenant_id,
        )
        session_factory = get_session_factory()
        async with session_factory() as session:
            qa_persistence = PostgresQAPersistence(session)
            tenant_repo = PostgresTenantConfigurationRepository(session)
            tenant_runtime = TenantConfigurationRuntime(repository=tenant_repo)
            llm_client = build_llm_client(settings, prefer_reasoning_model=True)

            # Component A: aggregate QA signals
            aggregator = QASignalAggregator(
                qa_persistence=qa_persistence,
                grounding_threshold=settings.TRAINER_GROUNDING_THRESHOLD,
                min_ticket_count=settings.TRAINER_MIN_TICKET_COUNT,
                window_days=settings.TRAINER_WINDOW_DAYS,
            )
            weak_categories = await aggregator.identify_weak_categories(
                tenant_id=tenant_id,
            )

            if not weak_categories:
                logger.info(
                    "trainer_no_weak_categories tenant=%s", tenant_id
                )
                return {
                    "status": "no_action",
                    "tenant_id": tenant_id,
                    "weak_categories": 0,
                    "proposals_submitted": 0,
                }

            logger.info(
                "trainer_weak_categories tenant=%s count=%d",
                tenant_id, len(weak_categories),
            )

            # Component B + C: for each weak category, run trainer and submit proposal
            proposals_submitted = 0
            for weak_cat in weak_categories:
                try:
                    submitted = await _process_weak_category(
                        weak_category=weak_cat,
                        tenant_runtime=tenant_runtime,
                        tenant_repo=tenant_repo,
                        llm_client=llm_client,
                        tenant_id=tenant_id,
                        session=session,
                    )
                    if submitted:
                        proposals_submitted += 1
                        await session.commit()
                except Exception:
                    logger.warning(
                        "trainer_category_failed tenant=%s category=%s",
                        tenant_id, weak_cat.category,
                        exc_info=True,
                    )

            return {
                "status": "completed",
                "tenant_id": tenant_id,
                "weak_categories": len(weak_categories),
                "proposals_submitted": proposals_submitted,
            }
    finally:
        set_current_tenant(None)


async def _process_weak_category(
    *,
    weak_category: WeakCategory,
    tenant_runtime: TenantConfigurationRuntime,
    tenant_repo: PostgresTenantConfigurationRepository,
    llm_client: Any,
    tenant_id: str,
    session: Any,
) -> bool:
    """Run KBTrainerAgent for one weak category and submit the proposal.

    Returns True if a proposal was submitted, False if skipped or failed.
    """
    # Load active SOP/POLICY docs for this tenant as KB context
    corpus_page = await tenant_repo.list_knowledge_documents(
        TenantKnowledgeDocumentQuery(
            review_status=None,  # approved docs only is default when None
            limit=20,
        ),
        expected_tenant_id=tenant_id,
    )
    # Filter to approved SOP/POLICY docs
    from app.tenant.enums import TenantKnowledgeReviewStatus
    current_kb_docs = [
        {
            "doc_id": str(doc.document_id),
            "title": doc.title,
            "content": doc.content,
        }
        for doc in corpus_page.items
        if doc.review_status == TenantKnowledgeReviewStatus.APPROVED
        and doc.document_type in (
            TenantKnowledgeDocumentType.SOP,
            TenantKnowledgeDocumentType.POLICY,
        )
    ]

    # Build input for KBTrainerAgent
    agent_input = AgentInput(
        tenant_id=tenant_id,
        session_id=f"trainer:{weak_category.category}:{tenant_id}",
        execution_id=f"trainer:{weak_category.category}:{datetime.now(timezone.utc).isoformat()}",
        content={
            "category": weak_category.category,
            "avg_semantic_grounding": weak_category.avg_semantic_grounding,
            "ticket_count": weak_category.ticket_count,
            "representative_cases": [
                {"case_id": cid, "ticket_text": "", "proposed_reply": "",
                 "semantic_grounding": weak_category.avg_semantic_grounding}
                for cid in weak_category.representative_case_ids
            ],
            "current_kb_docs": current_kb_docs,
        },
    )

    # Run KBTrainerAgent
    agent = KBTrainerAgent(
        llm_client=llm_client,
        tenant_configuration_repository=tenant_repo,
    )
    proposal = await agent.run(agent_input)

    if proposal.status != AgentProposalStatus.COMPLETED or proposal.output is None:
        logger.warning(
            "trainer_agent_failed tenant=%s category=%s status=%s reason=%s",
            tenant_id, weak_category.category,
            proposal.status.value, proposal.reason,
        )
        return False

    output = proposal.output
    improvement_type = output.get("improvement_type", "GAP_NOTICE")
    proposed_content = output.get("proposed_content") or ""
    gap_description = output.get("gap_description") or ""
    confidence = output.get("confidence", 0.0)
    evidence_case_ids = output.get("evidence_case_ids", [])

    # Build proposal title and content
    title = _proposal_title(weak_category.category, improvement_type)
    if improvement_type == "GAP_NOTICE":
        content = (
            f"[KB Trainer — GAP NOTICE]\n\n"
            f"Category: {weak_category.category}\n"
            f"Average semantic grounding: {weak_category.avg_semantic_grounding:.2f} "
            f"(threshold: {weak_category.metadata.get('threshold', 0.6)})\n"
            f"Tickets analysed: {weak_category.ticket_count}\n"
            f"Evidence cases: {', '.join(evidence_case_ids)}\n\n"
            f"Gap description:\n{gap_description or '(not specified)'}\n\n"
            f"Trainer confidence: {confidence:.2f}\n"
            f"[Human review required before any KB change]"
        )
    else:
        content = proposed_content or gap_description or "(no content generated)"

    if not content.strip():
        logger.info(
            "trainer_empty_proposal tenant=%s category=%s — skipping",
            tenant_id, weak_category.category,
        )
        return False

    # Component C: submit proposal via create_knowledge_document()
    # Requires an ApprovalRecord with status="approved" (system-generated).
    # This does NOT mean the KB document is approved — it means the PROPOSAL
    # submission itself is authorized by the trainer system identity.
    approval = _build_trainer_approval_record(
        tenant_id=tenant_id,
        category=weak_category.category,
        evidence_case_ids=evidence_case_ids,
        confidence=confidence,
    )

    try:
        await tenant_runtime.create_knowledge_document(
            tenant_id=tenant_id,
            title=title,
            content=content,
            document_type=_TRAINER_DOCUMENT_TYPE,
            uploaded_by=_TRAINER_PRINCIPAL_ID,
            status=TenantKnowledgeDocumentStatus.PENDING_INDEX,
            approval=approval,
        )
        logger.info(
            "trainer_proposal_submitted tenant=%s category=%s type=%s confidence=%.2f",
            tenant_id, weak_category.category, improvement_type, confidence,
        )
        return True
    except Exception:
        logger.warning(
            "trainer_kb_submit_failed tenant=%s category=%s",
            tenant_id, weak_category.category,
            exc_info=True,
        )
        return False


def _proposal_title(category: str, improvement_type: str) -> str:
    """Construct a deterministic, human-readable proposal title."""
    type_label = {
        "NEW_DOCUMENT": "New KB Article",
        "AMENDMENT": "KB Amendment",
        "GAP_NOTICE": "KB Gap Notice",
    }.get(improvement_type, "KB Improvement")
    return f"[Trainer] {type_label}: {category}"


def _build_trainer_approval_record(
    *,
    tenant_id: str,
    category: str,
    evidence_case_ids: list[str],
    confidence: float,
) -> Any:
    """Build an approved ApprovalRecord authorizing the trainer submission.

    This is the system-level authorization that lets the trainer's proposal
    enter the KB as a QUARANTINED document awaiting human review. It is NOT
    the human approval of the document content — that happens separately
    when a KB admin reviews the document and sets review_status=APPROVED.
    """
    from app.sop_intelligence import ApprovalRecord, ApprovalStatus

    approval_id = str(uuid.uuid5(
        uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890"),
        f"trainer:{tenant_id}:{category}:{datetime.now(timezone.utc).date().isoformat()}",
    ))
    # Use a placeholder document_id — will be overwritten by derive_knowledge_document_id
    return ApprovalRecord(
        approval_id=approval_id,
        tenant_id=tenant_id,
        document_id=approval_id,  # placeholder; actual doc_id derived by runtime
        proposed_change=f"KB trainer proposal for category '{category}'",
        evidence_sessions=tuple(evidence_case_ids[:10]),
        confidence=confidence,
        status=ApprovalStatus.APPROVED.value,
        proposed_by=_TRAINER_PRINCIPAL_ID,
        reviewed_by=_TRAINER_PRINCIPAL_ID,
        created_at=datetime.now(timezone.utc).isoformat(),
        metadata={
            "source": "kb_trainer_agent",
            "category": category,
            "evidence_case_ids": evidence_case_ids,
        },
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
        raise RuntimeError("trainer aggregation coroutine returned no result")
    return results[0]


@celery_app.task(  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator]
    name="trigger_kb_trainer_all_tenants",
    queue=QUEUE_TRAINER,
    bind=True,
    ignore_result=True,
    max_retries=1,
    default_retry_delay=60,
)
def trigger_kb_trainer_all_tenants(
    _self: Any,
    _enqueued_at: str | None = None,
) -> dict[str, object]:
    """Daily orchestrator: dispatch aggregate_qa_signals for every active tenant.

    Each tenant gets an independent aggregate_qa_signals task so failures are
    isolated. This is the scheduled entry point that was missing — without it
    the trainer loop never ran automatically.
    """
    del _enqueued_at
    try:
        return _run_async(
            _trigger_trainer_for_all_tenants(),
            tenant_id="platform",
        )
    except Exception as exc:
        logger.exception("trigger_kb_trainer_all_tenants_failed: %s", exc)
        return {"status": "error", "message": str(exc)}


async def _trigger_trainer_for_all_tenants() -> dict[str, object]:
    """Load every tenant that has active KB documents and dispatch the trainer."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        # Load all tenant IDs that have active KB documents
        # (no cross-tenant query needed — we just iterate all known tenants)
        from sqlalchemy import select, distinct
        from app.tenant.db.models import TenantKnowledgeDocumentRow
        stmt = select(distinct(TenantKnowledgeDocumentRow.tenant_id)).where(
            TenantKnowledgeDocumentRow.status.in_(["active", "pending_index"])
        )
        result = await session.execute(stmt)
        tenant_ids = [row[0] for row in result.fetchall()]

    dispatched = 0
    for tenant_id in tenant_ids:
        try:
            from typing import cast, Any as _Any
            cast(_Any, aggregate_qa_signals).apply_async(
                kwargs={"tenant_id": tenant_id},
            )
            dispatched += 1
        except Exception:
            logger.warning(
                "trigger_kb_trainer_dispatch_failed tenant=%s", tenant_id,
                exc_info=True,
            )

    logger.info(
        "trigger_kb_trainer_all_tenants_complete tenants=%d dispatched=%d",
        len(tenant_ids), dispatched,
    )
    return {
        "status": "completed",
        "tenants_found": len(tenant_ids),
        "dispatched": dispatched,
    }


__all__ = [
    "aggregate_qa_signals",
    "aggregate_qa_signals_runtime",
    "trigger_kb_trainer_all_tenants",
]

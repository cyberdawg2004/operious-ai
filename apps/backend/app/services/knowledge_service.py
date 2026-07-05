"""Tenant knowledge ingestion service boundary."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge.models import (
    KnowledgeAnalysisResult,
    KnowledgeIngestionResult,
    KnowledgeRetrievalResult,
)
from app.knowledge.runtime import KnowledgeRuntime
from app.tenant.enums import TenantKnowledgeDocumentType, TenantKnowledgeReviewStatus
from app.tenant.identity import TenantKnowledgeDocumentId
from app.tenant.persistence import TenantConfigurationRepository
from app.tenant.persistence.models import TenantKnowledgeDocumentQuery

if TYPE_CHECKING:
    from app.agents.governed.sop_contradiction import SOPContradictionAgent

logger = logging.getLogger(__name__)

_ANALYZABLE_TYPES = (
    TenantKnowledgeDocumentType.SOP,
    TenantKnowledgeDocumentType.POLICY,
)


class KnowledgeService:
    """Application service for tenant knowledge ingestion and retrieval."""

    def __init__(
        self,
        *,
        runtime: KnowledgeRuntime,
        session: AsyncSession,
        tenant_configuration_repository: TenantConfigurationRepository | None = None,
        sop_contradiction_agent: "SOPContradictionAgent | None" = None,
    ) -> None:
        self._runtime = runtime
        self._session = session
        self._tenant_repo = tenant_configuration_repository
        self._sop_contradiction_agent = sop_contradiction_agent

    async def ingest_document(
        self,
        *,
        tenant_id: str,
        document_id: TenantKnowledgeDocumentId,
    ) -> KnowledgeIngestionResult:
        result = await self._runtime.ingest_document(
            tenant_id=tenant_id,
            document_id=document_id,
        )
        await self._session.commit()
        return result

    async def retrieve(
        self,
        *,
        tenant_id: str,
        query: str,
        top_k: int,
        max_tokens: int | None,
        max_chunks_per_document: int | None,
        min_score: float | None,
    ) -> KnowledgeRetrievalResult:
        return await self._runtime.retrieve(
            tenant_id=tenant_id,
            query=query,
            top_k=top_k,
            max_tokens=max_tokens,
            max_chunks_per_document=max_chunks_per_document,
            min_score=min_score,
        )

    async def analyze_knowledge_base(
        self,
        *,
        tenant_id: str,
        document_types: list[str] | None = None,
    ) -> KnowledgeAnalysisResult:
        """Full KB analysis: contradictions, quarantine detail, and trainer dispatch.

        1. Load all APPROVED SOP/POLICY documents for this tenant.
        2. Surface any already-quarantined docs that have contradiction_metadata.
        3. Run SOPContradictionAgent pairwise across the active corpus to detect
           NEW cross-document conflicts not caught at individual ingest time.
        4. Enqueue aggregate_qa_signals for this tenant (trainer gap detection).

        Returns a structured report immediately. Trainer runs asynchronously.
        """
        from app.agents.governed.base import AgentInput, AgentProposalStatus

        repo = self._tenant_repo
        if repo is None:
            raise ValueError("tenant_configuration_repository required for KB analysis")

        # ── Step 1: load active corpus ────────────────────────────────
        allowed_types = set(document_types or [])
        page = await repo.list_knowledge_documents(
            TenantKnowledgeDocumentQuery(
                review_status=TenantKnowledgeReviewStatus.APPROVED,
                limit=50,
            ),
            expected_tenant_id=tenant_id,
        )
        corpus = [
            doc for doc in page.items
            if doc.document_type in _ANALYZABLE_TYPES
            and (not allowed_types or doc.document_type.value in allowed_types)
        ]

        # ── Step 2: surface already-quarantined docs with metadata ────
        quarantined_page = await repo.list_knowledge_documents(
            TenantKnowledgeDocumentQuery(
                review_status=TenantKnowledgeReviewStatus.QUARANTINED,
                limit=50,
            ),
            expected_tenant_id=tenant_id,
        )
        quarantined_with_detail = [
            {
                "document_id": str(doc.document_id),
                "title": doc.title,
                "document_type": doc.document_type.value,
                "contradiction_metadata": doc.contradiction_metadata,
            }
            for doc in quarantined_page.items
            if doc.contradiction_metadata is not None
            and doc.document_type in _ANALYZABLE_TYPES
        ]

        # ── Step 3: pairwise contradiction scan across active corpus ──
        agent = self._sop_contradiction_agent
        conflicts: list[dict[str, Any]] = []

        if agent is not None and len(corpus) >= 2:
            for i, doc_a in enumerate(corpus):
                # Build corpus excluding doc_a as "existing" docs
                other_docs = [
                    {
                        "doc_id": str(doc.document_id),
                        "title": doc.title,
                        "content": doc.content,
                    }
                    for j, doc in enumerate(corpus)
                    if j != i
                ]
                agent_input = AgentInput(
                    tenant_id=tenant_id,
                    session_id=f"analyze:{doc_a.document_id}",
                    execution_id=f"analyze:{doc_a.document_id}:scan",
                    content={
                        "new_document_id": str(doc_a.document_id),
                        "new_document_title": doc_a.title,
                        "new_document_type": doc_a.document_type.value,
                        "new_document_content": doc_a.content,
                        "corpus_documents": other_docs,
                    },
                )
                try:
                    proposal = await agent.run(agent_input)
                    if (
                        proposal.status == AgentProposalStatus.COMPLETED
                        and proposal.output is not None
                        and proposal.output.get("has_contradiction")
                    ):
                        for item in proposal.output.get("contradicting_documents", []):
                            # Find the contradicting doc title from the corpus
                            doc_b_id = item.get("doc_id", "")
                            doc_b_title = next(
                                (d.title for d in corpus if str(d.document_id) == doc_b_id),
                                doc_b_id,
                            )
                            # Deduplicate: skip if we already have this pair (b vs a)
                            already = any(
                                c["doc_a_id"] == doc_b_id and c["doc_b_id"] == str(doc_a.document_id)
                                for c in conflicts
                            )
                            if not already:
                                conflicts.append({
                                    "doc_a_id": str(doc_a.document_id),
                                    "doc_a_title": doc_a.title,
                                    "doc_b_id": doc_b_id,
                                    "doc_b_title": doc_b_title,
                                    "excerpt_a": item.get("excerpt", ""),
                                    "excerpt_b": item.get("contradicting_excerpt", ""),
                                    "contradiction_type": item.get("contradiction_type", ""),
                                    "confidence": float(item.get("confidence", 0.0)),
                                })
                except Exception:
                    logger.warning(
                        "analyze_contradiction_scan_failed tenant=%s doc=%s",
                        tenant_id, doc_a.document_id,
                        exc_info=True,
                    )

        # ── Step 4: enqueue trainer ───────────────────────────────────
        trainer_enqueued = _enqueue_trainer_for_tenant(tenant_id)

        await self._session.commit()

        return KnowledgeAnalysisResult(
            tenant_id=tenant_id,
            documents_analyzed=len(corpus),
            contradictions_found=len(conflicts),
            conflicts=conflicts,
            quarantined_with_detail=quarantined_with_detail,
            trainer_enqueued=trainer_enqueued,
            analyzed_at=datetime.now(timezone.utc),
        )


def _enqueue_trainer_for_tenant(tenant_id: str) -> bool:
    """Enqueue aggregate_qa_signals for this tenant. Returns True if enqueued."""
    try:
        from typing import cast, Any as _Any
        from app.workers.trainer_tasks import aggregate_qa_signals
        cast(_Any, aggregate_qa_signals).apply_async(
            kwargs={"tenant_id": tenant_id},
        )
        return True
    except Exception:
        logger.warning(
            "trainer_enqueue_failed tenant=%s", tenant_id, exc_info=True
        )
        return False


__all__ = ["KnowledgeService"]

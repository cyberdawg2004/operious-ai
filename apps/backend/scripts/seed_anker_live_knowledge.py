"""Seed the live Anker pilot support knowledge pack.

Run inside the deployed backend environment. The script writes tenant-owned
knowledge through the same runtime/repository path used by production, then
indexes each changed or inactive document.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import get_settings  # noqa: E402
from app.db.session import dispose_engine, get_session_factory  # noqa: E402
from app.db.tenant_context import set_current_tenant  # noqa: E402
from app.knowledge.chunking import DeterministicKnowledgeChunker  # noqa: E402
from app.knowledge.persistence import PostgresKnowledgeRepository  # noqa: E402
from app.knowledge.poisoning import PatternKnowledgeInjectionScanner  # noqa: E402
from app.knowledge.runtime import KnowledgeRuntime  # noqa: E402
from app.sop_intelligence import ApprovalRecord  # noqa: E402
from app.tenant.enums import (  # noqa: E402
    TenantKnowledgeDocumentStatus,
    TenantKnowledgeDocumentType,
    TenantKnowledgeReviewStatus,
)
from app.tenant.identity import TenantKnowledgeDocumentId  # noqa: E402
from app.tenant.persistence import TenantKnowledgeDocumentQuery  # noqa: E402
from app.tenant.persistence.postgres import (  # noqa: E402
    PostgresTenantConfigurationRepository,
)
from app.tenant.runtime import TenantConfigurationRuntime  # noqa: E402

DEFAULT_TENANT_ID: Final[str] = "anker-pilot"
UPLOADED_BY: Final[str] = "live-demo-knowledge-seeder"
ROOT = Path(__file__).resolve().parent / "anker_demo"


@dataclass(frozen=True, slots=True)
class DocumentSpec:
    title: str
    document_type: TenantKnowledgeDocumentType
    path: Path


@dataclass(frozen=True, slots=True)
class DocumentSeedResult:
    title: str
    document_id: str
    action: str
    status: str
    review_status: str
    version: int
    review_scan_flagged: bool
    ingestion: dict[str, object] | None = None


DOCUMENTS: Final[tuple[DocumentSpec, ...]] = (
    DocumentSpec(
        title="Anker Pilot Demo - Charging Issue Policy",
        document_type=TenantKnowledgeDocumentType.SOP,
        path=ROOT / "sops" / "anker_charging_issue_policy.md",
    ),
    DocumentSpec(
        title="Anker Pilot Demo - Returns And Refund Policy",
        document_type=TenantKnowledgeDocumentType.POLICY,
        path=ROOT / "sops" / "anker_returns_policy.md",
    ),
    DocumentSpec(
        title="Anker Pilot Demo - Warranty Terms",
        document_type=TenantKnowledgeDocumentType.POLICY,
        path=ROOT / "sops" / "anker_warranty_terms.md",
    ),
    DocumentSpec(
        title="Anker Pilot Demo - Escalation Matrix",
        document_type=TenantKnowledgeDocumentType.ESCALATION_MATRIX,
        path=ROOT / "sops" / "anker_escalation_matrix.md",
    ),
    DocumentSpec(
        title="Anker Pilot Demo - Product Defect Classification Guide",
        document_type=TenantKnowledgeDocumentType.PRODUCT_GUIDE,
        path=ROOT / "sops" / "anker_product_defect_classification.md",
    ),
    DocumentSpec(
        title="Anker Pilot Live - Power Bank Troubleshooting",
        document_type=TenantKnowledgeDocumentType.PRODUCT_GUIDE,
        path=ROOT / "live_support" / "anker_live_power_bank_troubleshooting.md",
    ),
    DocumentSpec(
        title="Anker Pilot Live - Safety And Recall Escalation",
        document_type=TenantKnowledgeDocumentType.ESCALATION_MATRIX,
        path=ROOT / "live_support" / "anker_live_safety_recall_escalation.md",
    ),
    DocumentSpec(
        title="Anker Pilot Live - Returns Warranty Policy",
        document_type=TenantKnowledgeDocumentType.POLICY,
        path=ROOT / "live_support" / "anker_live_returns_warranty_policy.md",
    ),
    DocumentSpec(
        title="Anker Pilot Live - Customer Response Playbook",
        document_type=TenantKnowledgeDocumentType.SOP,
        path=ROOT / "live_support" / "anker_live_customer_response_playbook.md",
    ),
)


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", default=DEFAULT_TENANT_ID)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--reingest", action="store_true")
    args = parser.parse_args(argv)

    tenant_id = args.tenant_id.strip()
    if not tenant_id:
        raise RuntimeError("--tenant-id must not be empty")

    set_current_tenant(tenant_id)
    settings = get_settings()
    session_factory = get_session_factory()

    async with session_factory() as session:
        tenant_repository = PostgresTenantConfigurationRepository(session)
        tenant_runtime = TenantConfigurationRuntime(repository=tenant_repository)
        knowledge_runtime = KnowledgeRuntime(
            repository=PostgresKnowledgeRepository(session),
            tenant_configuration_repository=tenant_repository,
            chunker=DeterministicKnowledgeChunker(
                target_size=settings.CHUNK_TARGET_SIZE,
                overlap=settings.CHUNK_OVERLAP,
                min_size=settings.CHUNK_MIN_SIZE,
            ),
            vector_index_name=settings.VECTOR_DEFAULT_INDEX,
            default_context_token_budget=settings.RAG_DEFAULT_CONTEXT_TOKEN_BUDGET,
        )
        injection_scanner = PatternKnowledgeInjectionScanner()

        existing_page = await tenant_runtime.list_knowledge_documents(
            tenant_id=tenant_id,
            query=TenantKnowledgeDocumentQuery(limit=500),
        )
        existing_by_title = {record.title: record for record in existing_page.items}

        results: list[DocumentSeedResult] = []
        for spec in DOCUMENTS:
            content = spec.path.read_text(encoding="utf-8")
            existing = existing_by_title.get(spec.title)
            action = "skipped"
            if existing is None:
                record = await tenant_runtime.create_knowledge_document(
                    tenant_id=tenant_id,
                    title=spec.title,
                    content=content,
                    document_type=spec.document_type,
                    uploaded_by=UPLOADED_BY,
                    approval=_approval(tenant_id=tenant_id, title=spec.title),
                )
                action = "created"
            elif args.force or existing.content != content:
                record = await tenant_runtime.update_knowledge_document(
                    tenant_id=tenant_id,
                    document_id=TenantKnowledgeDocumentId(existing.document_id),
                    content=content,
                    status=TenantKnowledgeDocumentStatus.PENDING_INDEX,
                    uploaded_by=UPLOADED_BY,
                    approval=_approval(tenant_id=tenant_id, title=spec.title),
                )
                action = "updated"
            else:
                record = existing

            review_scan = injection_scanner.scan(content)
            approved_before_ingest = False
            if (
                not review_scan.flagged
                and record.review_status is not TenantKnowledgeReviewStatus.APPROVED
            ):
                record = await tenant_runtime.update_knowledge_document(
                    tenant_id=tenant_id,
                    document_id=TenantKnowledgeDocumentId(record.document_id),
                    review_status=TenantKnowledgeReviewStatus.APPROVED,
                    uploaded_by=UPLOADED_BY,
                    approval=_approval(tenant_id=tenant_id, title=spec.title),
                )
                approved_before_ingest = True
                if action == "skipped":
                    action = "approved"

            should_ingest = (
                args.force
                or args.reingest
                or action in {"created", "updated"}
                or approved_before_ingest
                or record.status is not TenantKnowledgeDocumentStatus.ACTIVE
            )
            ingestion = None
            if should_ingest:
                result = await knowledge_runtime.ingest_document(
                    tenant_id=tenant_id,
                    document_id=record.document_id,
                )
                ingestion = {
                    "chunk_count": result.chunk_count,
                    "vector_count": result.vector_count,
                    "vector_index_name": result.vector_index_name,
                }
                refreshed = await tenant_repository.get_knowledge_document(
                    record.document_id,
                    expected_tenant_id=tenant_id,
                )
                if refreshed is not None:
                    record = refreshed

            results.append(
                DocumentSeedResult(
                    title=record.title,
                    document_id=str(record.document_id),
                    action=action,
                    status=record.status.value,
                    review_status=record.review_status.value,
                    version=record.version,
                    review_scan_flagged=review_scan.flagged,
                    ingestion=ingestion,
                )
            )

        await session.commit()

    await dispose_engine()
    print(
        json.dumps(
            {
                "tenant_id": tenant_id,
                "documents": [asdict(result) for result in results],
                "created": sum(1 for result in results if result.action == "created"),
                "updated": sum(1 for result in results if result.action == "updated"),
                "ingested": sum(1 for result in results if result.ingestion),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _approval(*, tenant_id: str, title: str) -> ApprovalRecord:
    slug = "-".join(title.lower().split())
    return ApprovalRecord(
        approval_id=f"live-demo-knowledge-{slug}",
        tenant_id=tenant_id,
        document_id=slug,
        proposed_change="Seed sourced Anker live-demo support knowledge.",
        evidence_sessions=(),
        confidence=1.0,
        status="approved",
        proposed_by=UPLOADED_BY,
        reviewed_by=UPLOADED_BY,
        created_at=datetime.now(timezone.utc).isoformat(),
        metadata={"origin": "live_demo_seed"},
    )


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

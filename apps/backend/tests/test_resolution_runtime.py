"""Resolution proposal runtime and safety invariants."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.resolution.enums import (
    ResolutionAutonomyDecision,
    ResolutionGovernanceVerdict,
    ResolutionProposalStatus,
    ResolutionSupervisorVerdict,
)
from app.resolution.persistence import (
    InMemoryResolutionProposalPersistence,
    PostgresResolutionProposalPersistence,
    ResolutionProposalQuery,
)
from app.runtime.resolution_runtime import (
    ResolutionProposalRequest,
    ResolutionRuntime,
    resolution_proposal_timeline_payload,
)
from app.tenant.db.models import TenantRow
from tests.conftest import requires_postgres, set_pg_rls_tenant

TENANT_ID = "tenant-resolution"
SESSION_ID = "11111111-1111-4111-8111-111111111111"
EXECUTION_ID = "22222222-2222-4222-8222-222222222222"
DISPATCH_ID = "33333333-3333-4333-8333-333333333333"
DIAGNOSTIC_EVENT_ID = "44444444-4444-4444-8444-444444444444"


def _citation() -> dict[str, object]:
    return {
        "rank": 1,
        "document_id": "55555555-5555-4555-8555-555555555555",
        "title": "Charging Troubleshooting SOP",
        "document_type": "sop",
        "document_status": "active",
        "score": 0.92,
        "chunk_ordinal": 0,
        "token_count": 128,
    }


def _immutable_citation() -> dict[str, object]:
    safe_excerpt = "Check USB-C cable fit before warranty replacement triage."
    citation = _citation()
    citation.update(
        {
            "citation_schema_version": 2,
            "chunk_id": "66666666-6666-4666-8666-666666666666",
            "vector_id": "77777777-7777-4777-8777-777777777777",
            "document_version": 3,
            "vector_index_name": "tenant_knowledge_default",
            "safe_excerpt": safe_excerpt,
            "safe_excerpt_sha256": hashlib.sha256(
                safe_excerpt.encode("utf-8")
            ).hexdigest(),
            "chunk_content_hash": "sha256:charging-sop-chunk",
        }
    )
    return citation


def _request(
    *,
    content: str = "My PowerCore stopped charging.",
    category: str = "charging_issue",
    confidence: float = 0.91,
    citations: list[dict[str, object]] | None = None,
) -> ResolutionProposalRequest:
    return ResolutionProposalRequest(
        tenant_id=TENANT_ID,
        session_id=SESSION_ID,
        execution_id=EXECUTION_ID,
        dispatch_id=DISPATCH_ID,
        diagnostic_event_id=DIAGNOSTIC_EVENT_ID,
        diagnostic_summary="Charging issue found.",
        diagnostic_category=category,
        diagnostic_confidence=confidence,
        original_content=content,
        retrieved_citations=citations if citations is not None else [_citation()],
    )


async def _ensure_committed_tenants(
    seed_engine: AsyncEngine | None,
    fallback_session: AsyncSession,
    *tenant_ids: str,
) -> None:
    if seed_engine is None:
        for tenant_id in tenant_ids:
            await fallback_session.merge(TenantRow(tenant_id=tenant_id))
        await fallback_session.flush()
        return

    async with seed_engine.begin() as connection:
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            for tenant_id in tenant_ids:
                await session.merge(TenantRow(tenant_id=tenant_id))
            await session.flush()
            await session.commit()
        finally:
            await session.close()


@pytest.mark.asyncio
async def test_safe_charging_issue_creates_send_eligible_proposal() -> None:
    persistence = InMemoryResolutionProposalPersistence()
    runtime = ResolutionRuntime(persistence=persistence)

    record = await runtime.create_proposal(_request())

    assert record.tenant_id == TENANT_ID
    assert record.resolution_category == "charging_issue"
    assert record.autonomy_decision is ResolutionAutonomyDecision.AUTO_APPROVED
    assert record.status is ResolutionProposalStatus.SEND_ELIGIBLE
    assert record.supervisor_verdict is ResolutionSupervisorVerdict.PASS
    assert record.governance_verdict is ResolutionGovernanceVerdict.ALLOW
    assert record.evidence
    assert "refund" not in record.proposed_customer_reply.lower()


@pytest.mark.asyncio
async def test_missing_citations_prevent_auto_approval() -> None:
    record = await ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence()
    ).create_proposal(_request(citations=[]))

    assert record.autonomy_decision is ResolutionAutonomyDecision.NEEDS_HUMAN_APPROVAL
    assert record.status is ResolutionProposalStatus.PENDING_HUMAN_APPROVAL
    assert record.governance_verdict is ResolutionGovernanceVerdict.REQUIRE_APPROVAL
    assert record.evidence == ()


@pytest.mark.asyncio
async def test_resolution_evidence_preserves_immutable_citation_fields() -> None:
    record = await ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence()
    ).create_proposal(_request(citations=[_immutable_citation()]))

    evidence = record.evidence[0]
    assert evidence["citation_schema_version"] == 2
    assert evidence["chunk_id"] == "66666666-6666-4666-8666-666666666666"
    assert evidence["vector_id"] == "77777777-7777-4777-8777-777777777777"
    assert evidence["document_version"] == 3
    assert evidence["vector_index_name"] == "tenant_knowledge_default"
    assert (
        evidence["safe_excerpt"]
        == "Check USB-C cable fit before warranty replacement triage."
    )
    assert evidence["safe_excerpt_sha256"] == hashlib.sha256(
        str(evidence["safe_excerpt"]).encode("utf-8")
    ).hexdigest()
    assert evidence["chunk_content_hash"] == "sha256:charging-sop-chunk"


@pytest.mark.asyncio
async def test_old_citation_payloads_still_normalize() -> None:
    record = await ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence()
    ).create_proposal(_request(citations=[_citation()]))

    evidence = record.evidence[0]
    assert evidence["document_id"] == _citation()["document_id"]
    assert evidence["title"] == "Charging Troubleshooting SOP"
    assert "chunk_id" not in evidence
    assert "safe_excerpt" not in evidence


@pytest.mark.asyncio
async def test_low_confidence_requires_human_approval() -> None:
    record = await ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence()
    ).create_proposal(_request(confidence=0.42))

    assert record.autonomy_decision is ResolutionAutonomyDecision.NEEDS_HUMAN_APPROVAL
    assert record.status is ResolutionProposalStatus.PENDING_HUMAN_APPROVAL
    assert record.supervisor_verdict is ResolutionSupervisorVerdict.NEEDS_HUMAN_REVIEW


@pytest.mark.asyncio
async def test_safety_smoke_fire_or_injury_requires_human_approval() -> None:
    record = await ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence()
    ).create_proposal(
        _request(
            content="The charger started smoking and caused a hand injury.",
            confidence=0.95,
        )
    )

    assert record.autonomy_decision is ResolutionAutonomyDecision.NEEDS_HUMAN_APPROVAL
    assert record.status is ResolutionProposalStatus.PENDING_HUMAN_APPROVAL
    assert record.governance_verdict is ResolutionGovernanceVerdict.ESCALATE


@pytest.mark.asyncio
async def test_resolution_proposal_reads_are_tenant_scoped() -> None:
    persistence = InMemoryResolutionProposalPersistence()
    record = await ResolutionRuntime(persistence=persistence).create_proposal(
        _request()
    )

    assert (
        await persistence.get_resolution_proposal(
            str(record.proposal_id),
            expected_tenant_id="tenant-other",
        )
        is None
    )
    page = await persistence.list_resolution_proposals(
        ResolutionProposalQuery(),
        expected_tenant_id="tenant-other",
    )
    assert page.total == 0


@pytest.mark.asyncio
@requires_postgres
async def test_postgres_resolution_persistence_enforces_tenant_rls(
    pg_session,
    pg_seed_engine,
) -> None:
    await _ensure_committed_tenants(
        pg_seed_engine,
        pg_session,
        TENANT_ID,
        "tenant-other",
    )
    await set_pg_rls_tenant(pg_session, TENANT_ID)
    persistence = PostgresResolutionProposalPersistence(pg_session)
    record = await ResolutionRuntime(persistence=persistence).create_proposal(
        _request()
    )

    assert (
        await persistence.get_resolution_proposal(
            str(record.proposal_id),
            expected_tenant_id=TENANT_ID,
        )
    ) is not None

    await set_pg_rls_tenant(pg_session, "tenant-other")
    assert (
        await persistence.get_resolution_proposal(
            str(record.proposal_id),
            expected_tenant_id="tenant-other",
        )
    ) is None
    assert (
        await persistence.get_resolution_proposal(
            str(record.proposal_id),
            expected_tenant_id=TENANT_ID,
        )
    ) is None


@pytest.mark.asyncio
async def test_resolution_timeline_payload_is_customer_safe_handoff() -> None:
    record = await ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence()
    ).create_proposal(_request())

    payload = resolution_proposal_timeline_payload(record)

    assert payload["proposal_id"] == str(record.proposal_id)
    assert payload["proposed_customer_reply"] == record.proposed_customer_reply
    assert payload["recommended_actions"] == [
        dict(action) for action in record.recommended_actions
    ]
    assert payload["evidence"] == [dict(item) for item in record.evidence]
    assert payload["send_eligible"] is True
    assert payload["requires_human_approval"] is False


def test_resolution_runtime_has_no_external_send_path() -> None:
    source = Path(
        "apps/backend/app/runtime/resolution_runtime.py"
    ).read_text(encoding="utf-8")
    forbidden = (
        "BoundaryEgressRuntime",
        ".emit(",
        ".send(",
        "Zendesk",
        "Twilio",
        "WhatsApp",
        "SMTP",
    )

    assert [token for token in forbidden if token in source] == []


def test_resolution_lineage_paths_do_not_use_uuid4() -> None:
    roots = (
        Path("apps/backend/app/resolution"),
        Path("apps/backend/app/runtime/resolution_runtime.py"),
    )
    violations: list[str] = []
    for root in roots:
        paths = [root] if root.is_file() else sorted(root.rglob("*.py"))
        for path in paths:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            uuid_module_names = {"uuid"}
            uuid4_names = {"uuid4"}
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == "uuid":
                            uuid_module_names.add(alias.asname or alias.name)
                elif isinstance(node, ast.ImportFrom) and node.module == "uuid":
                    for alias in node.names:
                        if alias.name == "uuid4":
                            violations.append(
                                f"{path}:{node.lineno} imports uuid4 directly"
                            )
                            uuid4_names.add(alias.asname or alias.name)
                elif isinstance(node, ast.Call):
                    func = node.func
                    if (
                        isinstance(func, ast.Attribute)
                        and func.attr == "uuid4"
                        and isinstance(func.value, ast.Name)
                        and func.value.id in uuid_module_names
                    ):
                        violations.append(
                            f"{path}:{node.lineno} calls {func.value.id}.uuid4()"
                        )
                    elif isinstance(func, ast.Name) and func.id in uuid4_names:
                        violations.append(f"{path}:{node.lineno} calls uuid4()")

    assert violations == []


def test_resolution_migration_enables_force_rls() -> None:
    source = Path(
        "apps/backend/migrations/versions/0041_resolution_proposals.py"
    ).read_text(encoding="utf-8")

    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "operious_tenant_rls_allows(tenant_id)" in source


def test_resolution_tenant_fk_migration_checks_orphans_and_adds_fk() -> None:
    source = Path(
        "apps/backend/migrations/versions/0042_resolution_proposal_tenant_fk.py"
    ).read_text(encoding="utf-8")

    assert (
        "down_revision: Union[str, None] = \"0041_resolution_proposals\""
        in source
    )
    assert "orphan_rows" in source
    assert "WHERE t.tenant_id IS NULL" in source
    assert "tenant_id values exist" in source
    assert "create_foreign_key" in source
    assert "\"resolution_proposals\"" in source
    assert "\"tenants\"" in source
    assert "[\"tenant_id\"]" in source
    assert "ondelete=\"RESTRICT\"" in source


def test_worker_hooks_resolution_after_diagnostic_success() -> None:
    source = Path("apps/backend/app/workers/agent_tasks.py").read_text(
        encoding="utf-8"
    )

    completed_index = source.index("event_type=_COMPLETED")
    resolution_index = source.index("_append_resolution_proposal_after_diagnostic")
    complete_execution_index = source.index("complete_execution")
    assert completed_index < resolution_index < complete_execution_index
    assert "_RESOLUTION_CREATED = \"resolution_proposal_created\"" in source
    assert "_RESOLUTION_FAILED = \"resolution_proposal_failed\"" in source

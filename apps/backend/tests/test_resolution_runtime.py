"""Resolution proposal runtime and safety invariants."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

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
) -> None:
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

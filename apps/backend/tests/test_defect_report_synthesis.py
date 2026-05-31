"""Defect report synthesis tests."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.defect_report_agent import (
    DefectReportSynthesisAgent,
    derive_defect_report_id,
)
from app.cognition.defect_report_models import DefectReportLLMOutput
from app.cognition.exceptions import CognitionLLMProviderError
from app.cognition.llm import DiagnosticLLMMessage
from app.cognition.models import DiagnosticLLMCompletion, DiagnosticLLMUsage
from app.events import InMemoryOperationalEventPersistence
from app.execution import ExecutionResultEnvelope, ExecutionState
from app.execution.db.models import ExecutionRow
from app.execution.enums import ExecutionKind
from app.governance.decisions import GovernanceDecision, PolicyEvaluationResult
from app.governance.enums import Decision, EnforcementStage
from app.governance.envelopes import GovernanceEnvelope
from app.governance.tracing import GovernanceTrace
from app.runtime.db.models import DefectClusterRow, DefectReportRow
from app.workers.defect_cluster_tasks import scan_for_defect_clusters_runtime
from app.runtime.defect_cluster_runtime import CLUSTER_THRESHOLD
from app.tenant.db.models import TenantRow
from tests.conftest import requires_postgres, set_pg_rls_tenant

_NOW = datetime(2026, 5, 30, 10, tzinfo=timezone.utc)

pytestmark = [pytest.mark.asyncio, requires_postgres]


async def test_defect_report_schema_rejects_invalid_confidence() -> None:
    with pytest.raises(ValueError):
        DefectReportLLMOutput(**{**_valid_report_payload(), "confidence": 1.5})


async def test_defect_report_schema_rejects_unknown_fields() -> None:
    with pytest.raises(ValueError):
        DefectReportLLMOutput(**{**_valid_report_payload(), "unknown": "x"})


async def test_synthesis_fetches_evidence_from_executions(
    pg_session: AsyncSession,
) -> None:
    tenant_id = "tenant-report-evidence"
    summaries = (
        "Unit stops charging after two minutes.",
        "Battery pack overheats while plugged in.",
        "Replacement cable does not restore charging.",
    )
    execution_ids = await _seed_executions(
        pg_session,
        tenant_id=tenant_id,
        summaries=summaries,
    )
    cluster = await _seed_cluster(
        pg_session,
        tenant_id=tenant_id,
        category="charging_issue",
        execution_ids=execution_ids,
    )
    llm = _RecordingReportLLM()
    agent = DefectReportSynthesisAgent(
        session=pg_session,
        llm_client=llm,
        governance_runtime=_GovernanceStub(Decision.ALLOW),
        event_persistence=InMemoryOperationalEventPersistence(),
        now=lambda: _NOW,
    )

    await agent.synthesize(cluster=cluster, expected_tenant_id=tenant_id)

    prompt = llm.prompts[0]
    for summary in summaries:
        assert summary in prompt


async def test_synthesis_governance_allow_persists_allowed_report(
    pg_session: AsyncSession,
) -> None:
    tenant_id = "tenant-report-allow"
    execution_ids = await _seed_executions(
        pg_session,
        tenant_id=tenant_id,
        summaries=("Recurring USB-C charging failure.",),
    )
    cluster = await _seed_cluster(
        pg_session,
        tenant_id=tenant_id,
        category="charging_issue",
        execution_ids=execution_ids,
    )
    agent = DefectReportSynthesisAgent(
        session=pg_session,
        llm_client=_RecordingReportLLM(),
        governance_runtime=_GovernanceStub(Decision.ALLOW),
        event_persistence=InMemoryOperationalEventPersistence(),
        now=lambda: _NOW,
    )

    report_id = await agent.synthesize(
        cluster=cluster,
        expected_tenant_id=tenant_id,
    )
    report = await pg_session.get(DefectReportRow, uuid.UUID(report_id))
    refreshed_cluster = await pg_session.get(DefectClusterRow, cluster.cluster_id)

    assert report is not None
    assert report.governance_status == "allowed"
    assert refreshed_cluster is not None
    assert refreshed_cluster.status == "reported"


async def test_synthesis_governance_deny_persists_blocked_report(
    pg_session: AsyncSession,
) -> None:
    tenant_id = "tenant-report-deny"
    execution_ids = await _seed_executions(
        pg_session,
        tenant_id=tenant_id,
        summaries=("Recurring power-button failure.",),
    )
    cluster = await _seed_cluster(
        pg_session,
        tenant_id=tenant_id,
        category="product_defect",
        execution_ids=execution_ids,
    )
    agent = DefectReportSynthesisAgent(
        session=pg_session,
        llm_client=_RecordingReportLLM(),
        governance_runtime=_GovernanceStub(Decision.DENY),
        event_persistence=InMemoryOperationalEventPersistence(),
        now=lambda: _NOW,
    )

    report_id = await agent.synthesize(
        cluster=cluster,
        expected_tenant_id=tenant_id,
    )
    report = await pg_session.get(DefectReportRow, uuid.UUID(report_id))
    refreshed_cluster = await pg_session.get(DefectClusterRow, cluster.cluster_id)

    assert report is not None
    assert report.governance_status == "blocked"
    assert report.dispatched_at is None
    assert refreshed_cluster is not None
    assert refreshed_cluster.status == "detected"


async def test_synthesis_llm_failure_does_not_crash_beat_task(
    pg_session: AsyncSession,
) -> None:
    tenant_id = "tenant-report-llm-fail"
    await _seed_executions(
        pg_session,
        tenant_id=tenant_id,
        summaries=tuple(
            f"Charging failure evidence {index}"
            for index in range(CLUSTER_THRESHOLD)
        ),
        base_time=datetime.now(timezone.utc),
    )
    failing_agent = DefectReportSynthesisAgent(
        session=pg_session,
        llm_client=_FailingReportLLM(),
        governance_runtime=_GovernanceStub(Decision.ALLOW),
        event_persistence=InMemoryOperationalEventPersistence(),
        now=lambda: _NOW,
    )

    result = await scan_for_defect_clusters_runtime(
        tenant_ids=(tenant_id,),
        session=pg_session,
        synthesis_agent=failing_agent,
    )
    await set_pg_rls_tenant(pg_session, tenant_id)
    cluster = (
        await pg_session.execute(
            select(DefectClusterRow).where(
                DefectClusterRow.tenant_id == tenant_id
            )
        )
    ).scalar_one()

    assert result["status"] == "completed"
    assert cluster.status == "detected"


async def test_defect_report_tenant_isolation(pg_session: AsyncSession) -> None:
    tenant_a = "tenant-report-a"
    tenant_b = "tenant-report-b"
    cluster = await _seed_cluster(
        pg_session,
        tenant_id=tenant_a,
        category="charging_issue",
        execution_ids=(),
    )
    report_id = derive_defect_report_id(cluster.cluster_id)
    pg_session.add(
        DefectReportRow(
            report_id=report_id,
            tenant_id=tenant_a,
            cluster_id=cluster.cluster_id,
            title="Tenant A report",
            executive_summary="Tenant A summary",
            failure_pattern="Tenant A pattern",
            customer_impact="Tenant A impact",
            root_cause_hypothesis="Tenant A hypothesis",
            recommended_actions=["Inspect units"],
            confidence=0.8,
            evidence_quality="medium",
            incident_count=1,
            governance_status="allowed",
            metadata_json={},
        )
    )
    await pg_session.flush()
    await _ensure_tenant(pg_session, tenant_b)
    try:
        await pg_session.execute(text("SET LOCAL ROLE operious_app_test"))
        await set_pg_rls_tenant(pg_session, tenant_b)
        visible_count = int(
            (
                await pg_session.execute(
                    select(func.count()).select_from(DefectReportRow)
                )
            ).scalar_one()
        )
    finally:
        await pg_session.execute(text("RESET ROLE"))

    assert visible_count == 0


async def _seed_executions(
    session: AsyncSession,
    *,
    tenant_id: str,
    summaries: tuple[str, ...],
    base_time: datetime | None = None,
) -> tuple[str, ...]:
    await _ensure_tenant(session, tenant_id)
    anchor = base_time or _NOW
    execution_ids: list[str] = []
    for index, summary in enumerate(summaries):
        execution_id = uuid.uuid5(
            uuid.UUID("157ab4f4-5a54-5ef1-83a5-c7bd55754b68"),
            f"{tenant_id}|{summary}|{index}",
        )
        execution_ids.append(str(execution_id))
        session.add(
            ExecutionRow(
                execution_id=execution_id,
                kind=ExecutionKind.DIAGNOSTIC_AGENT.value,
                dispatch_id=f"dispatch-{execution_id}",
                session_id=f"session-{execution_id}",
                tenant_id=tenant_id,
                state=ExecutionState.COMPLETED.value,
                attempt_count=1,
                requested_at=anchor - timedelta(minutes=10 - index),
                completed_at=anchor - timedelta(minutes=9 - index),
                diagnostic_category="charging_issue",
                diagnostic_confidence=0.9,
                result=ExecutionResultEnvelope(
                    diagnostic_category="charging_issue",
                    diagnostic_confidence=0.9,
                    diagnostic_summary=summary,
                ).to_dict(),
                metadata_json={},
            )
        )
    await session.flush()
    return tuple(execution_ids)


async def _seed_cluster(
    session: AsyncSession,
    *,
    tenant_id: str,
    category: str,
    execution_ids: tuple[str, ...],
) -> DefectClusterRow:
    await _ensure_tenant(session, tenant_id)
    cluster_id = uuid.uuid5(
        uuid.UUID("cc47e4ec-61c4-521d-9565-833bd2738f28"),
        f"{tenant_id}|{category}|{','.join(execution_ids)}",
    )
    cluster = DefectClusterRow(
        cluster_id=cluster_id,
        tenant_id=tenant_id,
        category=category,
        execution_count=max(1, len(execution_ids)),
        window_hours=24,
        window_start=_NOW - timedelta(hours=1),
        window_end=_NOW,
        threshold_used=CLUSTER_THRESHOLD,
        sku_hint=None,
        failure_step_hint=None,
        status="detected",
        metadata_json={"execution_ids": list(execution_ids)},
    )
    session.add(cluster)
    await session.flush()
    return cluster


async def _ensure_tenant(session: AsyncSession, tenant_id: str) -> None:
    await set_pg_rls_tenant(session, tenant_id)
    await session.merge(TenantRow(tenant_id=tenant_id))
    await session.flush()


def _valid_report_payload() -> dict[str, Any]:
    return {
        "title": "Charging defect pattern",
        "executive_summary": "Several charging failures share a pattern.",
        "affected_category": "charging_issue",
        "incident_count": 3,
        "failure_pattern": "Charging stops under load.",
        "customer_impact": "Customers cannot reliably charge devices.",
        "technical_root_cause_hypothesis": "USB-C power path instability.",
        "recommended_actions": ["Inspect returned units"],
        "confidence": 0.8,
        "evidence_quality": "medium",
    }


class _RecordingReportLLM:
    provider_name = "test-provider"
    model_name = "test-report-model"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def complete(
        self,
        *,
        system_prompt: str,
        messages: tuple[DiagnosticLLMMessage, ...],
        max_output_tokens: int,
        temperature: float,
        tenant_id: str | None = None,
    ) -> DiagnosticLLMCompletion:
        del system_prompt, max_output_tokens, temperature, tenant_id
        prompt = "\n".join(message.content for message in messages)
        self.prompts.append(prompt)
        text = json.dumps(_valid_report_payload())
        return DiagnosticLLMCompletion(
            provider=self.provider_name,
            model=self.model_name,
            text=text,
            usage=DiagnosticLLMUsage(
                prompt_tokens=10,
                completion_tokens=10,
                total_tokens=20,
            ),
            raw_metadata={},
        )


class _FailingReportLLM(_RecordingReportLLM):
    async def complete(
        self,
        *,
        system_prompt: str,
        messages: tuple[DiagnosticLLMMessage, ...],
        max_output_tokens: int,
        temperature: float,
        tenant_id: str | None = None,
    ) -> DiagnosticLLMCompletion:
        del system_prompt, messages, max_output_tokens, temperature, tenant_id
        raise CognitionLLMProviderError("provider unavailable")


class _GovernanceStub:
    def __init__(self, decision: Decision) -> None:
        self.decision = decision
        self.contexts: list[object] = []

    async def evaluate(self, context: object) -> GovernanceEnvelope:
        self.contexts.append(context)
        decision_id = uuid.uuid5(
            uuid.UUID("c94761d8-6bb7-5522-ac33-c6188a43ffea"),
            f"{self.decision.value}|{len(self.contexts)}",
        )
        result = PolicyEvaluationResult(
            policy_name="test",
            rule_id="test",
            decision=self.decision,
        )
        governance_decision = GovernanceDecision(
            decision_id=decision_id,
            decision=self.decision,
            stage=EnforcementStage.PRE_EXECUTION,
            policy_chain_id="test",
            evaluated_rules=(result,),
            violations=(),
            restrictions=(),
            reason="test decision",
            decided_at=_NOW,
        )
        trace = GovernanceTrace(
            decision_id=decision_id,
            request_id=None,
            stage=EnforcementStage.PRE_EXECUTION,
            action="ai.defect_report_synthesis",
            resource="cluster:test",
            actor="agent:defect_report",
            tenant_id=None,
            started_at=_NOW,
            ended_at=_NOW,
            latency_ms=0.0,
            status="ok",
            final_decision=self.decision,
            policy_chain_id="test",
            policy_traces=(),
            rule_count=1,
            violation_count=0,
            restriction_count=0,
            subject_kind="defect_cluster",
        )
        return GovernanceEnvelope(trace=trace, decision=governance_decision)

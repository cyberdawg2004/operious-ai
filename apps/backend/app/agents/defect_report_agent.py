"""Defect report synthesis agent."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, ClassVar, FrozenSet, Protocol, cast

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.cognition.defect_report_models import DefectReportLLMOutput
from app.cognition.exceptions import CognitionLLMProviderError
from app.cognition.llm import (
    DiagnosticLLMClient,
    DiagnosticLLMMessage,
    message_text,
)
from app.cognition.models import DiagnosticLLMCompletion, DiagnosticLLMUsage
from app.events import (
    EventCausality,
    EventChronology,
    OperationalEvent,
    OperationalSubstrate,
    derive_event_id,
)
from app.events.persistence import (
    OperationalEventPersistenceProtocol,
    PostgresOperationalEventPersistence,
)
from app.execution import ExecutionResultEnvelope, PostgresExecutionPersistence
from app.execution.identity import as_execution_id
from app.governance.context import GovernanceContext
from app.governance.decisions import PolicyEvaluationResult
from app.governance.enforcement.handlers import (
    AllowHandler,
    DegradeHandler,
    DenyHandler,
    EnforcementHandlerRegistry,
    EscalateHandler,
    RedactHandler,
    RequireApprovalHandler,
)
from app.governance.enforcement.runtime import GovernanceRuntime
from app.governance.enums import Decision, EnforcementStage, ViolationSeverity
from app.governance.evaluators.engine import PolicyEvaluationEngine
from app.governance.policies.base import BaseGovernancePolicy
from app.governance.policies.chain import PolicyChain
from app.governance.subjects.base import SubjectKind
from app.governance.subjects.cluster import ClusterGovernanceSubject
from app.governance.envelopes import GovernanceEnvelope
from app.governance.capability.acts import OperationalAct
from app.identity import coerce_tenant_id
from app.runtime.db.models import DefectClusterRow, DefectReportRow

MAX_EVIDENCE_EXECUTIONS = 20
_REPORT_NAMESPACE_NAME = "defect_report_synthesis"

_SYSTEM_PROMPT = (
    "You are a hardware product quality engineer analyzing customer "
    "support data to identify defect patterns. You must respond only "
    "with valid JSON matching this schema: {schema}"
)


@dataclass(frozen=True, slots=True)
class DefectReportSynthesisConfig:
    max_output_tokens: int = 1024
    temperature: float = 0.0


class GovernanceEvaluator(Protocol):
    async def evaluate(self, context: GovernanceContext) -> GovernanceEnvelope: ...


class DefectReportSynthesisAgent:
    """Synthesizes engineering defect reports from detected clusters."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        llm_client: DiagnosticLLMClient,
        execution_repo: PostgresExecutionPersistence | None = None,
        governance_runtime: GovernanceEvaluator | None = None,
        event_persistence: OperationalEventPersistenceProtocol | None = None,
        config: DefectReportSynthesisConfig | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._session = session
        self._llm_client = llm_client
        self._execution_repo = execution_repo or PostgresExecutionPersistence(session)
        self._governance = governance_runtime or _defect_report_governance_runtime()
        self._event_persistence = (
            event_persistence
            if event_persistence is not None
            else PostgresOperationalEventPersistence(session)
        )
        self._config = config or DefectReportSynthesisConfig()
        self._now = now or _utcnow

    async def synthesize(
        self,
        *,
        cluster: DefectClusterRow,
        expected_tenant_id: str,
    ) -> str:
        """Generate, govern, persist, and event a defect report."""

        if cluster.tenant_id != expected_tenant_id:
            raise ValueError("cluster tenant_id does not match expected_tenant_id")

        report_id = derive_defect_report_id(cluster.cluster_id)
        existing = await self._session.get(DefectReportRow, report_id)
        if existing is not None:
            return str(report_id)

        summaries = await self._diagnostic_summaries(cluster)
        prompt = _render_user_prompt(cluster=cluster, summaries=summaries)
        completion = await self._complete_llm(
            system_prompt=_render_system_prompt(),
            messages=(DiagnosticLLMMessage(role="user", content=prompt),),
            tenant_id=cluster.tenant_id,
        )
        output = _parse_output(completion.text)
        governance = await self._govern_report(
            cluster=cluster,
            output=output,
            completion=completion,
            prompt=prompt,
        )
        allowed = (
            governance.is_ok
            and governance.decision is not None
            and governance.decision.decision is Decision.ALLOW
        )
        status = "allowed" if allowed else "blocked"
        decision_id = (
            governance.decision.decision_id
            if governance.decision is not None
            else None
        )
        inserted = await self._persist_report(
            report_id=report_id,
            cluster=cluster,
            output=output,
            completion=completion,
            governance_decision_id=decision_id,
            governance_status=status,
            evidence_summaries=summaries,
            prompt=prompt,
        )
        if inserted and allowed:
            cluster.status = "reported"
            await self._session.flush()
        if inserted:
            await self._event_persistence.append_event(
                _defect_report_generated_event(
                    report_id=report_id,
                    cluster=cluster,
                    output=output,
                    governance_status=status,
                    governance_decision_id=decision_id,
                    occurred_at=self._now(),
                )
            )
        return str(report_id)

    async def _diagnostic_summaries(
        self,
        cluster: DefectClusterRow,
    ) -> tuple[str, ...]:
        summaries: list[str] = []
        execution_ids = _cluster_execution_ids(cluster)
        for execution_id in execution_ids[-MAX_EVIDENCE_EXECUTIONS:]:
            execution = await self._execution_repo.get_execution(
                as_execution_id(execution_id),
                expected_tenant_id=cluster.tenant_id,
            )
            if execution is None:
                continue
            envelope = ExecutionResultEnvelope.from_dict(
                execution.result.to_dict()
            )
            if envelope.diagnostic_summary:
                summaries.append(envelope.diagnostic_summary)
        return tuple(summaries)

    async def _complete_llm(
        self,
        *,
        system_prompt: str,
        messages: tuple[DiagnosticLLMMessage, ...],
        tenant_id: str,
    ) -> DiagnosticLLMCompletion:
        try:
            return await self._llm_client.complete(
                system_prompt=system_prompt,
                messages=messages,
                max_output_tokens=self._config.max_output_tokens,
                temperature=self._config.temperature,
                tenant_id=tenant_id,
            )
        except TypeError as exc:
            if "tenant_id" not in str(exc):
                raise
            return await self._llm_client.complete(
                system_prompt=system_prompt,
                messages=messages,
                max_output_tokens=self._config.max_output_tokens,
                temperature=self._config.temperature,
            )

    async def _govern_report(
        self,
        *,
        cluster: DefectClusterRow,
        output: DefectReportLLMOutput,
        completion: DiagnosticLLMCompletion,
        prompt: str,
    ) -> GovernanceEnvelope:
        decision_seed = _defect_report_governance_seed(
            tenant_id=cluster.tenant_id,
            cluster_id=cluster.cluster_id,
            report_id=derive_defect_report_id(cluster.cluster_id),
            model=completion.model,
            prompt_sha256=_sha256_text(prompt),
            completion_sha256=_sha256_text(completion.text),
        )
        return await self._governance.evaluate(
            GovernanceContext(
                stage=EnforcementStage.PRE_EXECUTION,
                action="ai.defect_report_synthesis",
                resource=f"cluster:{cluster.cluster_id}",
                actor="agent:defect_report",
                tenant_id=coerce_tenant_id(cluster.tenant_id),
                subject=ClusterGovernanceSubject(
                    cluster_id=str(cluster.cluster_id),
                    category=cluster.category,
                    tenant_id=cluster.tenant_id,
                    incident_count=cluster.execution_count,
                    evidence_quality=output.evidence_quality,
                    metadata={
                        "report_title": output.title,
                        "confidence": output.confidence,
                    },
                ),
                metadata={
                    "governance.decision_seed": decision_seed,
                    "report_id": str(derive_defect_report_id(cluster.cluster_id)),
                },
            )
        )

    async def _persist_report(
        self,
        *,
        report_id: uuid.UUID,
        cluster: DefectClusterRow,
        output: DefectReportLLMOutput,
        completion: DiagnosticLLMCompletion,
        governance_decision_id: uuid.UUID | None,
        governance_status: str,
        evidence_summaries: tuple[str, ...],
        prompt: str,
    ) -> bool:
        row = DefectReportRow(
            report_id=report_id,
            tenant_id=cluster.tenant_id,
            cluster_id=cluster.cluster_id,
            title=output.title,
            executive_summary=output.executive_summary,
            failure_pattern=output.failure_pattern,
            customer_impact=output.customer_impact,
            root_cause_hypothesis=output.technical_root_cause_hypothesis,
            recommended_actions=list(output.recommended_actions),
            confidence=output.confidence,
            evidence_quality=output.evidence_quality,
            incident_count=output.incident_count,
            governance_decision_id=governance_decision_id,
            governance_status=governance_status,
            llm_model=completion.model,
            cognition_audit_id=None,
            metadata_json={
                "cluster_category": cluster.category,
                "affected_category": output.affected_category,
                "llm_provider": completion.provider,
                "prompt_sha256": _sha256_text(prompt),
                "completion_sha256": _sha256_text(completion.text),
                "evidence_execution_ids": list(_cluster_execution_ids(cluster)),
                "evidence_summary_count": len(evidence_summaries),
            },
        )
        try:
            async with self._session.begin_nested():
                self._session.add(row)
                await self._session.flush()
        except IntegrityError:
            return False
        return True


class DeterministicDefectReportLLMClient:
    """Deterministic local report LLM for tests and offline workers."""

    provider_name = "operious-deterministic-llm"
    model_name = "operious-defect-report-local-v1"

    async def complete(
        self,
        *,
        system_prompt: str,
        messages: Sequence[DiagnosticLLMMessage],
        max_output_tokens: int,
        temperature: float,
        tenant_id: str | None = None,
    ) -> DiagnosticLLMCompletion:
        del system_prompt, max_output_tokens, temperature, tenant_id
        prompt = "\n".join(message_text(message.content) for message in messages)
        incident_count = max(1, prompt.count("\n") // 8)
        payload = {
            "title": "Detected recurring hardware defect pattern",
            "executive_summary": (
                "Customer support diagnostics show a recurring defect "
                "pattern requiring engineering review."
            ),
            "affected_category": _prompt_category(prompt),
            "incident_count": incident_count,
            "failure_pattern": "Multiple cases share the same diagnostic category.",
            "customer_impact": (
                "Customers experience repeat product failures and require support."
            ),
            "technical_root_cause_hypothesis": (
                "The pattern may originate from a shared component or batch process."
            ),
            "recommended_actions": [
                "Review recent support cases for shared SKU and batch signals.",
                "Inspect returned units for common component-level failure.",
            ],
            "confidence": 0.72,
            "evidence_quality": "medium",
        }
        text = json.dumps(payload, sort_keys=True)
        prompt_tokens = max(1, len(prompt) // 4)
        completion_tokens = max(1, len(text) // 4)
        return DiagnosticLLMCompletion(
            provider=self.provider_name,
            model=self.model_name,
            text=text,
            usage=DiagnosticLLMUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            ),
            raw_metadata={"deterministic": True},
        )


@dataclass(frozen=True, slots=True)
class DefectReportSynthesisPolicy(BaseGovernancePolicy):
    """Baseline report synthesis governance for cluster subjects."""

    name: ClassVar[str] = "defect_report_synthesis"
    supported_stages: ClassVar[FrozenSet[EnforcementStage]] = frozenset(
        {EnforcementStage.PRE_EXECUTION}
    )
    applicable_subject_kinds: ClassVar[FrozenSet[SubjectKind]] = frozenset(
        {SubjectKind.CLUSTER}
    )

    async def evaluate(
        self,
        context: GovernanceContext,
    ) -> Sequence[PolicyEvaluationResult]:
        subject = context.subject
        if not isinstance(subject, ClusterGovernanceSubject):
            return (
                PolicyEvaluationResult(
                    policy_name=self.name,
                    rule_id="subject_not_cluster",
                    decision=Decision.DENY,
                    severity=ViolationSeverity.CRITICAL,
                    reason="defect report synthesis requires cluster subject",
                ),
            )
        if subject.incident_count < 1:
            return (
                PolicyEvaluationResult(
                    policy_name=self.name,
                    rule_id="no_incidents",
                    decision=Decision.DENY,
                    severity=ViolationSeverity.HIGH,
                    reason="defect report synthesis requires at least one incident",
                ),
            )
        if subject.evidence_quality not in {"high", "medium", "low"}:
            return (
                PolicyEvaluationResult(
                    policy_name=self.name,
                    rule_id="invalid_evidence_quality",
                    decision=Decision.DENY,
                    severity=ViolationSeverity.HIGH,
                    reason="evidence_quality must be high, medium, or low",
                ),
            )
        return (
            PolicyEvaluationResult(
                policy_name=self.name,
                rule_id="cluster_report_synthesis_allowed",
                decision=Decision.ALLOW,
                severity=ViolationSeverity.LOW,
                reason="cluster report synthesis input is well formed",
                metadata={
                    "cluster_id": subject.cluster_id,
                    "incident_count": subject.incident_count,
                },
            ),
        )


def derive_defect_report_id(cluster_id: uuid.UUID | str) -> uuid.UUID:
    namespace = cluster_id if isinstance(cluster_id, uuid.UUID) else uuid.UUID(cluster_id)
    return uuid.uuid5(namespace, _REPORT_NAMESPACE_NAME)


def _defect_report_governance_runtime() -> GovernanceRuntime:
    registry = EnforcementHandlerRegistry()
    for handler in (
        AllowHandler(),
        DenyHandler(),
        RedactHandler(),
        DegradeHandler(),
        EscalateHandler(),
        RequireApprovalHandler(),
    ):
        registry.register(handler)
    return GovernanceRuntime(
        engine=PolicyEvaluationEngine(),
        handler_registry=registry,
        chains={
            EnforcementStage.PRE_EXECUTION: PolicyChain(
                chain_id="cognition.defect_report.pre_execution",
                stage=EnforcementStage.PRE_EXECUTION,
                policies=(DefectReportSynthesisPolicy(),),
            )
        },
    )


def _defect_report_generated_event(
    *,
    report_id: uuid.UUID,
    cluster: DefectClusterRow,
    output: DefectReportLLMOutput,
    governance_status: str,
    governance_decision_id: uuid.UUID | None,
    occurred_at: datetime,
) -> OperationalEvent:
    runtime_instance_id = uuid.uuid5(report_id, "operational_event_runtime")
    sequence = 0
    event_id = derive_event_id(
        operational_act=OperationalAct.DEFECT_REPORT_GENERATED.value,
        substrate=OperationalSubstrate.SUPERVISOR.value,
        runtime_instance_id=runtime_instance_id,
        sequence=sequence,
        tenant_id=cluster.tenant_id,
        parent_event_id=None,
    )
    return OperationalEvent(
        event_id=event_id,
        operational_act=OperationalAct.DEFECT_REPORT_GENERATED,
        substrate=OperationalSubstrate.SUPERVISOR,
        causality=EventCausality(root_event_id=event_id),
        chronology=EventChronology(
            runtime_instance_id=runtime_instance_id,
            sequence=sequence,
            occurred_at=occurred_at,
        ),
        tenant_id=cluster.tenant_id,
        metadata={
            "report_id": str(report_id),
            "cluster_id": str(cluster.cluster_id),
            "category": cluster.category,
            "governance_status": governance_status,
            "governance_decision_id": (
                str(governance_decision_id)
                if governance_decision_id is not None
                else None
            ),
            "incident_count": output.incident_count,
            "evidence_quality": output.evidence_quality,
        },
    )


def _cluster_execution_ids(cluster: DefectClusterRow) -> tuple[str, ...]:
    raw = cluster.metadata_json.get("execution_ids")
    if not isinstance(raw, list):
        return ()
    raw_values = cast(list[object], raw)
    execution_ids: list[str] = []
    for value in raw_values:
        try:
            execution_ids.append(str(uuid.UUID(str(value))))
        except (TypeError, ValueError):
            continue
    return tuple(execution_ids)


def _render_system_prompt() -> str:
    schema = json.dumps(
        DefectReportLLMOutput.model_json_schema(),
        sort_keys=True,
        separators=(",", ":"),
    )
    return _SYSTEM_PROMPT.replace("{schema}", schema)


def _render_user_prompt(
    *,
    cluster: DefectClusterRow,
    summaries: tuple[str, ...],
) -> str:
    numbered = "\n".join(
        f"{index}. {summary}" for index, summary in enumerate(summaries, start=1)
    )
    if not numbered:
        numbered = "No diagnostic summaries were available."
    return "\n\n".join(
        (
            (
                f'Analyze the following {len(summaries)} customer support '
                f'cases for product category "{cluster.category}" and write '
                "a technical engineering defect report."
            ),
            "Customer case summaries:",
            numbered,
            (
                "Identify the common failure pattern, assess customer impact, "
                "hypothesize technical root cause, and recommend actions."
            ),
        )
    )


def _parse_output(text: str) -> DefectReportLLMOutput:
    try:
        raw = json.loads(_extract_json(text))
    except json.JSONDecodeError as exc:
        raise CognitionLLMProviderError(
            "defect report model returned invalid JSON"
        ) from exc
    if not isinstance(raw, dict):
        raise CognitionLLMProviderError(
            "defect report model returned non-object JSON"
        )
    try:
        return DefectReportLLMOutput.model_validate(cast(dict[str, Any], raw))
    except ValidationError as exc:
        raise CognitionLLMProviderError(
            "defect report model output failed schema validation"
        ) from exc


def _extract_json(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        return stripped
    return stripped[start : end + 1]


def _defect_report_governance_seed(
    *,
    tenant_id: str,
    cluster_id: uuid.UUID,
    report_id: uuid.UUID,
    model: str,
    prompt_sha256: str,
    completion_sha256: str,
) -> str:
    return "cognition.defect_report.output|" + json.dumps(
        {
            "cluster_id": str(cluster_id),
            "completion_sha256": completion_sha256,
            "model": model,
            "prompt_sha256": prompt_sha256,
            "report_id": str(report_id),
            "tenant_id": tenant_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _prompt_category(prompt: str) -> str:
    marker = 'product category "'
    start = prompt.find(marker)
    if start == -1:
        return "unknown_issue"
    start += len(marker)
    end = prompt.find('"', start)
    if end == -1:
        return "unknown_issue"
    return prompt[start:end] or "unknown_issue"


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


__all__ = [
    "DefectReportSynthesisAgent",
    "DefectReportSynthesisConfig",
    "DefectReportSynthesisPolicy",
    "DeterministicDefectReportLLMClient",
    "MAX_EVIDENCE_EXECUTIONS",
    "derive_defect_report_id",
]

"""Central governance gate for resolution proposal communication."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any, ClassVar, FrozenSet, Mapping, Sequence, cast

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
from app.governance.persistence import BaseGovernanceRepository
from app.governance.policies.base import BaseGovernancePolicy
from app.governance.policies.chain import PolicyChain
from app.governance.subjects.base import SubjectKind
from app.governance.subjects.communication import CommunicationGovernanceSubject
from app.identity import coerce_tenant_id
from app.resolution.enums import ResolutionGovernanceVerdict
from app.resolution.identity import derive_resolution_outbound_draft_id
from app.runtime.grounding import (
    GroundingChecker,
    GroundingCheckRequest,
)
from app.runtime.money_goods_commitment import money_or_goods_commitment_kinds
from app.runtime.resolution_autonomy_policy import (
    ResolutionAutonomyPolicy,
    resolve_resolution_autonomy_policy,
)
from app.runtime.resolution_runtime import (
    ResolutionGovernanceGateProtocol,
    ResolutionGovernanceGateRequest,
    ResolutionGovernanceGateResult,
)
from app.tenant.persistence import TenantConfigurationRepository

_CHAIN_ID = "resolution.communication.pre_execution"
_ACTION = "resolution.proposal.prepare"
_CUSTOMER_REPLY_SEND_ACTION = "customer_reply.send"
_CHANNEL = "resolution/proposal"
_SUMMARY_MAX_CHARS = 480
_CORRELATION_NAMESPACE = uuid.UUID("2b7b4f5a-0002-4b01-9001-000000000001")

_SEVERE_LOCAL_REASONS = frozenset(
    {
        "safety_risk",
        "legal_or_chargeback_risk",
        "fraud_risk",
    }
)


class ResolutionCommunicationPolicy(BaseGovernancePolicy):
    """Central governance policy for prepared resolution communications."""

    name: ClassVar[str] = "resolution.communication"
    supported_stages: ClassVar[FrozenSet[EnforcementStage]] = frozenset(
        {EnforcementStage.PRE_EXECUTION}
    )
    applicable_subject_kinds: ClassVar[FrozenSet[SubjectKind]] = frozenset(
        {SubjectKind.COMMUNICATION}
    )

    def __init__(
        self,
        *,
        tenant_configuration_repository: TenantConfigurationRepository | None = None,
    ) -> None:
        self._repository = tenant_configuration_repository

    async def evaluate(
        self,
        context: GovernanceContext,
    ) -> Sequence[PolicyEvaluationResult]:
        subject = context.subject
        if not isinstance(subject, CommunicationGovernanceSubject):
            return (_deny("communication_subject_required"),)
        if context.tenant_id is None or subject.tenant_id is None:
            return (_deny("tenant_required"),)
        if str(context.tenant_id) != subject.tenant_id:
            return (
                _deny(
                    "tenant_mismatch",
                    metadata={
                        "context_tenant_id": str(context.tenant_id),
                        "subject_tenant_id": subject.tenant_id,
                    },
                ),
            )
        metadata = dict(subject.metadata)
        if not _metadata_str(metadata, "request_id") and not subject.request_id:
            return (_deny("request_id_required"),)
        if not _metadata_str(metadata, "proposal_id"):
            return (_deny("proposal_id_required"),)
        if not _metadata_str(metadata, "session_id"):
            return (_deny("session_id_required"),)
        if not _metadata_str(metadata, "execution_id"):
            return (_deny("execution_id_required"),)
        if not _metadata_str(metadata, "dispatch_id"):
            return (_deny("dispatch_id_required"),)
        evidence_count = _metadata_int(metadata, "evidence_count")
        if evidence_count is None or evidence_count <= 0:
            return (_deny("evidence_required"),)
        if not _metadata_str(metadata, "proposed_reply_sha256"):
            return (_deny("proposed_reply_hash_required"),)
        if not _metadata_str(metadata, "original_content_sha256"):
            return (_deny("original_content_hash_required"),)
        local_status = _metadata_str(metadata, "local_status")
        if local_status is None:
            return (_deny("local_status_required"),)
        local_autonomy = _metadata_str(metadata, "local_autonomy_decision")
        if local_autonomy is None:
            return (_deny("local_autonomy_decision_required"),)
        severe_flags = _severe_flags(metadata, subject.escalation_flags)
        if severe_flags:
            return (
                _deny(
                    "severe_resolution_risk",
                    severity=ViolationSeverity.CRITICAL,
                    metadata={"flags": list(severe_flags)},
                ),
            )

        category = _metadata_str(metadata, "resolution_category") or ""
        money_or_goods_commitment_present = bool(
            _metadata_str_list(metadata, "money_or_goods_commitment_kinds")
        )
        autonomy_policy = await resolve_resolution_autonomy_policy(
            repository=self._repository,
            tenant_id=subject.tenant_id,
        )
        approval_rule = _approval_rule(
            category=category,
            local_status=local_status,
            local_autonomy=local_autonomy,
            local_governance=_metadata_str(metadata, "local_governance_verdict"),
            local_supervisor=_metadata_str(metadata, "local_supervisor_verdict"),
            money_or_goods_commitment_present=money_or_goods_commitment_present,
            autonomy_policy=autonomy_policy,
        )
        if approval_rule is not None:
            return (_require_approval(approval_rule),)
        return (
            PolicyEvaluationResult(
                policy_name=ResolutionCommunicationPolicy.name,
                rule_id="resolution_communication_allowed",
                decision=Decision.ALLOW,
                severity=ViolationSeverity.LOW,
                reason="resolution proposal passed central communication governance",
            ),
        )


class GroundingPolicy(BaseGovernancePolicy):
    """Governance policy that blocks ungrounded customer-facing claims."""

    name: ClassVar[str] = "resolution.grounding"
    supported_stages: ClassVar[FrozenSet[EnforcementStage]] = frozenset(
        {EnforcementStage.PRE_EXECUTION}
    )
    applicable_subject_kinds: ClassVar[FrozenSet[SubjectKind]] = frozenset(
        {SubjectKind.COMMUNICATION}
    )

    def __init__(self, *, checker: GroundingChecker | None = None) -> None:
        self._checker = checker

    async def evaluate(
        self,
        context: GovernanceContext,
    ) -> Sequence[PolicyEvaluationResult]:
        subject = context.subject
        if not isinstance(subject, CommunicationGovernanceSubject):
            return (_grounding_deny("communication_subject_required"),)
        metadata = dict(subject.metadata)
        if bool(metadata.get("reply_is_preapproved_template")):
            # A tenant-authored, dual-control-approved verdict-override
            # template (see ResolutionGovernanceGateRequest.reply_is_
            # preapproved_template) is not LLM-drafted free text: its
            # factual claims are grounded in the resolution verdict that
            # gated its rendering (e.g. the warranty eligibility
            # determination), not in a retrievable KB span. Per-claim
            # KB-citation grounding does not apply to it -- there is no
            # knowledge document to cite for a runtime-computed fact like
            # "this order is within the warranty window". This exemption
            # is scoped exclusively to the override path; an LLM-drafted
            # reply with an uncited claim is graded exactly as before.
            return (
                PolicyEvaluationResult(
                    policy_name=GroundingPolicy.name,
                    rule_id="preapproved_template_exempt",
                    decision=Decision.ALLOW,
                    severity=ViolationSeverity.LOW,
                    reason=(
                        "reply is a tenant-authored, verdict-justified "
                        "override template, exempt from per-claim "
                        "KB-citation grounding"
                    ),
                ),
            )
        if self._checker is None:
            trace = _grounding_trace(
                status="ungrounded",
                ungrounded_claims=(
                    {
                        "reason": "grounding_checker_missing",
                        "claim": "",
                        "citation_ranks": [],
                    },
                ),
            )
            return (
                _grounding_deny(
                    "grounding_checker_missing",
                    metadata=_grounding_metadata(metadata, trace),
                ),
            )
        segments = _metadata_list(metadata, "reply_segments")
        evidence = _metadata_list(metadata, "evidence")
        result = await self._checker.check(
            GroundingCheckRequest(
                tenant_id=subject.tenant_id or str(context.tenant_id or ""),
                reply_segments=segments,
                evidence=evidence,
            )
        )
        if not result.allowed:
            return (
                _grounding_deny(
                    "ungrounded_claim",
                    metadata=_grounding_metadata(metadata, result.trace),
                ),
            )
        return (
            PolicyEvaluationResult(
                policy_name=GroundingPolicy.name,
                rule_id="grounding_claims_covered",
                decision=Decision.ALLOW,
                severity=ViolationSeverity.LOW,
                reason="all customer-facing claims cite approved knowledge spans",
                metadata={"grounding_trace": dict(result.trace)},
            ),
        )


class ResolutionGovernanceGate(ResolutionGovernanceGateProtocol):
    """Concrete central-governance adapter for resolution proposals."""

    def __init__(self, *, governance_runtime: GovernanceRuntime) -> None:
        self._governance = governance_runtime

    async def evaluate_resolution_proposal(
        self,
        request: ResolutionGovernanceGateRequest,
    ) -> ResolutionGovernanceGateResult:
        subject = _communication_subject(request)
        envelope = await self._governance.evaluate(
            GovernanceContext(
                stage=EnforcementStage.PRE_EXECUTION,
                action=_ACTION,
                resource=f"resolution_proposal:{request.proposal_id}",
                actor="agent:diagnostic",
                tenant_id=coerce_tenant_id(request.tenant_id),
                request_id=subject.request_id,
                subject=subject,
                correlation_id=_correlation_id(request),
                metadata={
                    **dict(subject.metadata),
                    "governance.decision_seed": _decision_seed(request),
                },
            )
        )
        if envelope.decision is None:
            return ResolutionGovernanceGateResult(
                governance_verdict=ResolutionGovernanceVerdict.DENY,
                governance_decision_id=envelope.trace.decision_id,
            )
        return ResolutionGovernanceGateResult(
            governance_verdict=ResolutionGovernanceVerdict(
                envelope.decision.decision.value
            ),
            governance_decision_id=envelope.decision.decision_id,
        )


def build_resolution_governance_runtime(
    *,
    persistence: BaseGovernanceRepository | None = None,
    grounding_checker: GroundingChecker | None = None,
    tenant_configuration_repository: TenantConfigurationRepository | None = None,
) -> GovernanceRuntime:
    """Build the standard central governance runtime for resolution."""

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
                chain_id=_CHAIN_ID,
                stage=EnforcementStage.PRE_EXECUTION,
                policies=(
                    ResolutionCommunicationPolicy(
                        tenant_configuration_repository=tenant_configuration_repository,
                    ),
                    GroundingPolicy(checker=grounding_checker),
                ),
            )
        },
        persistence=persistence,
    )


def _communication_subject(
    request: ResolutionGovernanceGateRequest,
) -> CommunicationGovernanceSubject:
    request_id = f"resolution:{request.proposal_id}"
    metadata = _subject_metadata(request=request, request_id=request_id)
    return CommunicationGovernanceSubject(
        channel=_CHANNEL,
        recipient_scope=f"tenant:{request.tenant_id}:session:{request.session_id}",
        content_summary=_content_summary(request),
        escalation_flags=_escalation_flags(request.local_reasons),
        request_id=request_id,
        tenant_id=request.tenant_id,
        metadata=metadata,
    )


def _subject_metadata(
    *,
    request: ResolutionGovernanceGateRequest,
    request_id: str,
) -> dict[str, object]:
    money_or_goods_commitment_kinds_metadata = money_or_goods_commitment_kinds(
        recommended_actions=request.recommended_actions,
        reply=request.proposed_customer_reply,
    )
    return {
        "request_id": request_id,
        "proposal_id": str(request.proposal_id),
        "draft_id": str(
            derive_resolution_outbound_draft_id(
                tenant_id=request.tenant_id,
                proposal_id=request.proposal_id,
            )
        ),
        "governed_action": _CUSTOMER_REPLY_SEND_ACTION,
        "source_channel": request.source_channel,
        "reply_recipient": request.reply_recipient,
        "reply_thread_context": request.reply_thread_context,
        "session_id": request.session_id,
        "execution_id": request.execution_id,
        "dispatch_id": request.dispatch_id,
        "diagnostic_event_id": request.diagnostic_event_id,
        "local_supervisor_verdict": request.local_supervisor_verdict.value,
        "local_governance_verdict": request.local_governance_verdict.value,
        "local_autonomy_decision": request.local_autonomy_decision.value,
        "local_status": request.local_status.value,
        "local_reasons": list(request.local_reasons),
        "evidence_count": len(request.evidence),
        "proposed_reply_sha256": _sha256_text(request.proposed_customer_reply),
        "original_content_sha256": _sha256_text(request.original_content),
        "resolution_category": request.resolution_category,
        "money_or_goods_commitment_kinds": list(
            money_or_goods_commitment_kinds_metadata
        ),
        "diagnostic_confidence": request.diagnostic_confidence,
        "diagnostic_summary": request.diagnostic_summary,
        "original_content_excerpt": request.original_content[:_SUMMARY_MAX_CHARS],
        "source_language": request.source_language,
        "reply_segments": [dict(segment) for segment in request.reply_segments],
        "evidence": [dict(item) for item in request.evidence],
        "reply_is_preapproved_template": request.reply_is_preapproved_template,
    }


def _content_summary(request: ResolutionGovernanceGateRequest) -> str:
    summary = (
        f"proposal_id={request.proposal_id}; "
        f"category={request.resolution_category}; "
        f"confidence={request.diagnostic_confidence:.3f}; "
        f"local_status={request.local_status.value}; "
        f"local_governance_verdict={request.local_governance_verdict.value}; "
        f"evidence_count={len(request.evidence)}"
    )
    if len(summary) <= _SUMMARY_MAX_CHARS:
        return summary
    return f"{summary[: _SUMMARY_MAX_CHARS - 3]}..."


def _escalation_flags(reasons: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(reason for reason in reasons if reason in _SEVERE_LOCAL_REASONS)


def _severe_flags(
    metadata: Mapping[str, object],
    escalation_flags: tuple[str, ...],
) -> tuple[str, ...]:
    reasons_value = metadata.get("local_reasons")
    reasons: list[str] = []
    if isinstance(reasons_value, list):
        for reason in cast(list[object], reasons_value):
            if isinstance(reason, str):
                reasons.append(reason)
    reasons.extend(escalation_flags)
    return tuple(sorted(set(reasons).intersection(_SEVERE_LOCAL_REASONS)))


def _approval_rule(
    *,
    category: str,
    local_status: str,
    local_autonomy: str,
    local_governance: str | None,
    local_supervisor: str | None,
    money_or_goods_commitment_present: bool,
    autonomy_policy: ResolutionAutonomyPolicy,
) -> str | None:
    if local_status != "auto_approved":
        return "local_status_not_auto_approved"
    if local_autonomy != "auto_approved":
        return "local_autonomy_not_auto_approved"
    if local_governance != "allow":
        return "local_governance_not_allow"
    if local_supervisor != "pass":
        return "local_supervisor_not_pass"
    if money_or_goods_commitment_present:
        return "money_or_goods_commitment_requires_human_approval"
    if category not in autonomy_policy.reply_auto_send_categories:
        return "resolution_category_not_auto_safe"
    return None


def _deny(
    rule_id: str,
    *,
    severity: ViolationSeverity = ViolationSeverity.HIGH,
    metadata: Mapping[str, object] | None = None,
) -> PolicyEvaluationResult:
    return PolicyEvaluationResult(
        policy_name=ResolutionCommunicationPolicy.name,
        rule_id=rule_id,
        decision=Decision.DENY,
        severity=severity,
        reason=f"resolution communication denied: {rule_id}",
        metadata=dict(metadata or {}),
    )


def _grounding_deny(
    rule_id: str,
    *,
    metadata: Mapping[str, object] | None = None,
) -> PolicyEvaluationResult:
    return PolicyEvaluationResult(
        policy_name=GroundingPolicy.name,
        rule_id=rule_id,
        decision=Decision.DENY,
        severity=ViolationSeverity.HIGH,
        reason=rule_id,
        metadata=dict(metadata or {}),
    )


def _require_approval(rule_id: str) -> PolicyEvaluationResult:
    return PolicyEvaluationResult(
        policy_name=ResolutionCommunicationPolicy.name,
        rule_id=rule_id,
        decision=Decision.REQUIRE_APPROVAL,
        severity=ViolationSeverity.MEDIUM,
        reason=f"resolution communication requires approval: {rule_id}",
    )


def _metadata_str(
    metadata: Mapping[str, object],
    key: str,
) -> str | None:
    value = metadata.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _metadata_int(
    metadata: Mapping[str, object],
    key: str,
) -> int | None:
    value = metadata.get(key)
    if isinstance(value, int):
        return value
    return None


def _metadata_list(
    metadata: Mapping[str, object],
    key: str,
) -> tuple[Mapping[str, Any], ...]:
    value = metadata.get(key)
    if not isinstance(value, list):
        return ()
    items: list[Mapping[str, Any]] = []
    for item in cast(list[object], value):
        if isinstance(item, Mapping):
            items.append(cast(Mapping[str, Any], item))
    return tuple(items)


def _metadata_str_list(
    metadata: Mapping[str, object],
    key: str,
) -> tuple[str, ...]:
    value = metadata.get(key)
    if not isinstance(value, list):
        return ()
    items: list[str] = []
    for item in cast(list[object], value):
        if isinstance(item, str) and item.strip():
            items.append(item.strip())
    return tuple(items)


def _grounding_trace(
    *,
    status: str,
    ungrounded_claims: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    return {
        "schema_version": "2.1",
        "status": status,
        "approved_knowledge_found": [],
        "ungrounded_claims": [dict(claim) for claim in ungrounded_claims],
    }


def _grounding_metadata(
    subject_metadata: Mapping[str, object],
    trace: Mapping[str, Any],
) -> dict[str, object]:
    handoff = {
        "ticket_no": _metadata_str(subject_metadata, "session_id"),
        "issue": _metadata_str(subject_metadata, "original_content_excerpt"),
        "escalation": "ungrounded_claim",
        "description": (
            "A generated customer-facing reply contained a claim that could "
            "not be traced to an approved knowledge span."
        ),
        "recommendation": (
            "A human reviewer should answer from approved SOP knowledge or "
            "update the approved knowledge base before automation resumes."
        ),
        "grounding_trace": dict(trace),
    }
    return {
        "structured_handoff": handoff,
        "grounding_trace": dict(trace),
    }


def _decision_seed(request: ResolutionGovernanceGateRequest) -> str:
    return (
        "resolution|"
        f"tenant:{request.tenant_id}|"
        f"proposal:{request.proposal_id}|"
        f"stage:{request.evaluation_stage.value}|"
        "governance"
    )


def _correlation_id(request: ResolutionGovernanceGateRequest) -> uuid.UUID:
    seed = "|".join(
        (
            request.tenant_id,
            request.session_id,
            request.execution_id,
            request.dispatch_id,
            str(request.proposal_id),
        )
    )
    return uuid.uuid5(_CORRELATION_NAMESPACE, seed)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = [
    "GroundingPolicy",
    "ResolutionCommunicationPolicy",
    "ResolutionGovernanceGate",
    "build_resolution_governance_runtime",
]

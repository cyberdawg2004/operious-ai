"""Governance policy for LLM-produced diagnostic output."""

from __future__ import annotations

from typing import ClassVar, FrozenSet, Sequence

from app.governance.context import GovernanceContext
from app.governance.decisions import PolicyEvaluationResult
from app.governance.enums import Decision, EnforcementStage, ViolationSeverity
from app.governance.policies.base import BaseGovernancePolicy
from app.governance.subjects.base import SubjectKind
from app.governance.subjects.execution import ExecutionGovernanceSubject


class LLMDiagnosticOutputPolicy(BaseGovernancePolicy):
    """Fail-closed governance for diagnostic model output."""

    name: ClassVar[str] = "cognition.llm_diagnostic_output"
    supported_stages: ClassVar[FrozenSet[EnforcementStage]] = frozenset(
        {EnforcementStage.PRE_EXECUTION}
    )
    applicable_subject_kinds: ClassVar[FrozenSet[SubjectKind]] = frozenset(
        {SubjectKind.EXECUTION}
    )

    def __init__(self, *, require_citations: bool = False) -> None:
        self._require_citations = require_citations

    async def evaluate(
        self,
        context: GovernanceContext,
    ) -> Sequence[PolicyEvaluationResult]:
        subject = context.subject
        if not isinstance(subject, ExecutionGovernanceSubject):
            return (_deny("execution_subject_required", "execution subject required"),)
        metadata = dict(subject.metadata)
        if context.tenant_id is None or subject.tenant_id is None:
            return (_deny("tenant_required", "diagnostic output requires tenant scope"),)
        if str(context.tenant_id) != subject.tenant_id:
            return (_deny("tenant_mismatch", "tenant scope mismatch"),)
        if metadata.get("semantic_valid") is not True:
            return (
                _deny(
                    "semantic_preservation_failed",
                    "diagnostic output failed semantic preservation",
                ),
            )
        confidence = metadata.get("confidence")
        if not isinstance(confidence, float) or not 0.0 <= confidence <= 1.0:
            return (_deny("confidence_invalid", "confidence must be in [0, 1]"),)
        category = metadata.get("category")
        if not isinstance(category, str) or not category.strip():
            return (_deny("category_required", "diagnostic category is required"),)
        if self._require_citations and subject.citation_count <= 0:
            return (
                _deny(
                    "citation_required",
                    "diagnostic output must be grounded in SOP citations",
                ),
            )
        return (
            PolicyEvaluationResult(
                policy_name=self.name,
                rule_id="diagnostic_output_allowed",
                decision=Decision.ALLOW,
                severity=ViolationSeverity.LOW,
                reason="diagnostic model output passed governance gate",
                metadata={
                    "citation_count": subject.citation_count,
                    "model": metadata.get("model"),
                    "provider": metadata.get("provider"),
                },
            ),
        )


def _deny(rule_id: str, reason: str) -> PolicyEvaluationResult:
    return PolicyEvaluationResult(
        policy_name=LLMDiagnosticOutputPolicy.name,
        rule_id=rule_id,
        decision=Decision.DENY,
        severity=ViolationSeverity.HIGH,
        reason=reason,
    )


__all__ = ["LLMDiagnosticOutputPolicy"]

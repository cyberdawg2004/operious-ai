"""Built-in reference governance policies.

Sprint I Hardening: every builtin now operates on **typed governance
subjects** — no more `context.subject["query"]`. Each policy
declares `applicable_subject_kinds`; the engine routes policies on
applicable kinds only.

Reference policies shipped:

* `TenantScopePolicy`       — DENY when tenant_id is not in an
                              allowed set. Applies to RETRIEVAL +
                              EXECUTION subjects.
* `MaxQueryLengthPolicy`    — DENY when query exceeds configured
                              length. Applies to RETRIEVAL subjects.
* `ContentDenylistPolicy`   — REDACT individual candidates whose
                              content matches a denylisted substring.
                              Applies to RETRIEVAL subjects (operates
                              at POST_RETRIEVAL stage).

These exist to:

1. Demonstrate the typed-subject policy contract.
2. Be the test fixtures the governance test suite drives.
3. Cover the DENY + REDACT decision classes (precedence + restriction
   aggregation paths).

Real-world policies plug in behind the same contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, FrozenSet, Sequence

from app.governance.context import GovernanceContext
from app.governance.decisions import PolicyEvaluationResult
from app.governance.enums import (
    Decision,
    EnforcementStage,
    RestrictionKind,
    ViolationSeverity,
)
from app.governance.policies.base import BaseGovernancePolicy
from app.governance.subjects.base import SubjectKind
from app.governance.subjects.retrieval import RetrievalGovernanceSubject
from app.governance.value_objects import RuntimeRestriction


# ─── TenantScopePolicy ───────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class TenantScopePolicy(BaseGovernancePolicy):
    """DENY when the subject's `tenant_id` is not in `allowed_tenants`.

    If `allowed_tenants` is empty, the policy ALLOWs every tenant —
    the default permissive behaviour. Deployments pin a non-empty
    allowlist at composition time when they need scoping.

    Reads `tenant_id` from the typed subject (Retrieval or Execution).
    For other subject kinds, the policy falls back to
    `context.tenant_id`.
    """

    allowed_tenants: FrozenSet[str] = frozenset()
    name: ClassVar[str] = "tenant_scope"
    supported_stages: ClassVar[FrozenSet[EnforcementStage]] = frozenset(
        {
            EnforcementStage.PRE_REQUEST,
            EnforcementStage.PRE_RETRIEVAL,
            EnforcementStage.PRE_EXECUTION,
        }
    )
    applicable_subject_kinds: ClassVar[FrozenSet[SubjectKind]] = frozenset(
        {
            SubjectKind.RETRIEVAL,
            SubjectKind.EXECUTION,
            SubjectKind.GENERIC,
        }
    )

    async def evaluate(
        self,
        context: GovernanceContext,
    ) -> Sequence[PolicyEvaluationResult]:
        # Empty allowlist = operator-explicit permissive default.
        # The behaviour is retained (operators may deliberately
        # configure no scoping), but the result is tagged with
        # `permissive_default` metadata so audits can detect every
        # ALLOW that came from an unconfigured allowlist — closing
        # the "is this intentional or misconfigured?" forensic gap.
        if not self.allowed_tenants:
            return (
                PolicyEvaluationResult(
                    policy_name=self.name,
                    rule_id="open_allowlist",
                    decision=Decision.ALLOW,
                    severity=ViolationSeverity.LOW,
                    reason="no tenant allowlist configured",
                    metadata={
                        "permissive_default": True,
                        "config_missing": "allowed_tenants",
                    },
                ),
            )

        # Read tenant_id from the typed subject when possible; fall
        # back to context.tenant_id otherwise (covers GENERIC).
        tenant_id = _tenant_id_for(context)

        if tenant_id is None:
            return (
                PolicyEvaluationResult(
                    policy_name=self.name,
                    rule_id="tenant_missing",
                    decision=Decision.DENY,
                    severity=ViolationSeverity.HIGH,
                    reason="tenant_id is required by tenant_scope policy",
                ),
            )
        if tenant_id not in self.allowed_tenants:
            return (
                PolicyEvaluationResult(
                    policy_name=self.name,
                    rule_id="tenant_not_allowed",
                    decision=Decision.DENY,
                    severity=ViolationSeverity.HIGH,
                    reason=f"tenant {tenant_id!r} is not allowlisted",
                    metadata={"tenant_id": tenant_id},
                ),
            )
        return (
            PolicyEvaluationResult(
                policy_name=self.name,
                rule_id="tenant_allowed",
                decision=Decision.ALLOW,
                severity=ViolationSeverity.LOW,
                reason="tenant in allowlist",
            ),
        )


# ─── MaxQueryLengthPolicy ─────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class MaxQueryLengthPolicy(BaseGovernancePolicy):
    """DENY when the retrieval subject's `query` exceeds `max_length`.

    Reads `subject.query` directly — typed access, no dict lookups.
    The policy is RETRIEVAL-only by `applicable_subject_kinds`; the
    engine skips it for any other subject kind.
    """

    max_length: int = 4000
    name: ClassVar[str] = "max_query_length"
    supported_stages: ClassVar[FrozenSet[EnforcementStage]] = frozenset(
        {EnforcementStage.PRE_RETRIEVAL}
    )
    applicable_subject_kinds: ClassVar[FrozenSet[SubjectKind]] = frozenset(
        {SubjectKind.RETRIEVAL}
    )

    async def evaluate(
        self,
        context: GovernanceContext,
    ) -> Sequence[PolicyEvaluationResult]:
        # Engine guarantees subject is RetrievalGovernanceSubject here.
        subject = context.subject
        assert isinstance(subject, RetrievalGovernanceSubject)
        query = subject.query
        if not query:
            # Symmetry with `TenantScopePolicy.tenant_missing`: a
            # required field is missing → DENY (fail-closed).
            # Core Law 4 prohibits asymmetric fail-open on the same
            # constitutional class.
            return (
                PolicyEvaluationResult(
                    policy_name=self.name,
                    rule_id="query_missing",
                    decision=Decision.DENY,
                    severity=ViolationSeverity.HIGH,
                    reason=(
                        "retrieval subject is missing required `query`; "
                        "substrate refuses to bound an unspecified query"
                    ),
                ),
            )
        if len(query) > self.max_length:
            return (
                PolicyEvaluationResult(
                    policy_name=self.name,
                    rule_id="query_too_long",
                    decision=Decision.DENY,
                    severity=ViolationSeverity.MEDIUM,
                    reason=(
                        f"query length {len(query)} exceeds max {self.max_length}"
                    ),
                    metadata={
                        "query_length": len(query),
                        "max_length": self.max_length,
                    },
                ),
            )
        return (
            PolicyEvaluationResult(
                policy_name=self.name,
                rule_id="query_within_bounds",
                decision=Decision.ALLOW,
                severity=ViolationSeverity.LOW,
                reason="query within bounds",
            ),
        )


# ─── ContentDenylistPolicy ────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ContentDenylistPolicy(BaseGovernancePolicy):
    """REDACT individual retrieval candidates with denylisted content.

    Operationally this is the **contract** — emitting REDACT plus
    matching restrictions. The actual filtering happens in the
    `RedactionGuardrail` (separation: policies emit verdicts;
    guardrails act). This separation matters because the same REDACT
    decision can be enforced differently depending on transport.

    The policy reads `subject.retrieval_candidates` (a tuple of
    `CandidateSummary`) directly. Empty candidates → ALLOW; non-empty
    candidates → one REDACT per match plus a single ALLOW fallback if
    nothing matched.
    """

    denylist: tuple[str, ...] = ()
    name: ClassVar[str] = "content_denylist"
    supported_stages: ClassVar[FrozenSet[EnforcementStage]] = frozenset(
        {EnforcementStage.POST_RETRIEVAL}
    )
    applicable_subject_kinds: ClassVar[FrozenSet[SubjectKind]] = frozenset(
        {SubjectKind.RETRIEVAL}
    )

    async def evaluate(
        self,
        context: GovernanceContext,
    ) -> Sequence[PolicyEvaluationResult]:
        if not self.denylist:
            # Empty denylist = operator-explicit permissive default.
            # Tagged as `permissive_default` so audits can detect
            # every ALLOW that came from an unconfigured denylist.
            return (
                PolicyEvaluationResult(
                    policy_name=self.name,
                    rule_id="open_denylist",
                    decision=Decision.ALLOW,
                    severity=ViolationSeverity.LOW,
                    reason="no denylisted terms configured",
                    metadata={
                        "permissive_default": True,
                        "config_missing": "denylist",
                    },
                ),
            )

        subject = context.subject
        assert isinstance(subject, RetrievalGovernanceSubject)
        candidates = subject.retrieval_candidates

        if not candidates:
            return (
                PolicyEvaluationResult(
                    policy_name=self.name,
                    rule_id="no_candidates",
                    decision=Decision.ALLOW,
                    severity=ViolationSeverity.LOW,
                    reason="no candidates to inspect",
                ),
            )

        results: list[PolicyEvaluationResult] = []
        for candidate in candidates:
            content = candidate.content
            chunk_id = candidate.chunk_id
            matched = next(
                (term for term in self.denylist if term in content),
                None,
            )
            if matched is None:
                continue
            results.append(
                PolicyEvaluationResult(
                    policy_name=self.name,
                    rule_id="denylisted_term_present",
                    decision=Decision.REDACT,
                    severity=ViolationSeverity.HIGH,
                    reason=f"chunk {chunk_id} contains denylisted term",
                    restrictions=(
                        RuntimeRestriction(
                            kind=RestrictionKind.CONTENT_REDACTION,
                            target=f"chunk_id:{chunk_id}",
                            value={"matched_term": matched},
                            reason="denylisted term in content",
                            policy_name=self.name,
                            rule_id="denylisted_term_present",
                        ),
                    ),
                    metadata={"chunk_id": chunk_id, "matched_term": matched},
                )
            )

        if not results:
            return (
                PolicyEvaluationResult(
                    policy_name=self.name,
                    rule_id="no_denylisted_terms",
                    decision=Decision.ALLOW,
                    severity=ViolationSeverity.LOW,
                    reason="no denylisted terms present",
                ),
            )
        return tuple(results)


# ─── Subject helpers ──────────────────────────────────────────────────


def _tenant_id_for(context: GovernanceContext) -> str | None:
    """Resolve the subject's tenant_id with typed-subject preference.

    Typed subjects (Retrieval, Execution) carry their own
    `tenant_id`; for other kinds we fall back to `context.tenant_id`.
    The resolution is a pure function — replay-safe.
    """
    subject = context.subject
    typed_tenant = getattr(subject, "tenant_id", None)
    if typed_tenant is not None:
        return typed_tenant
    return context.tenant_id


__all__ = [
    "TenantScopePolicy",
    "MaxQueryLengthPolicy",
    "ContentDenylistPolicy",
]

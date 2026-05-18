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

──────────────────────────────────────────────────────────────────
Wedge B5 — Constitutional class taxonomy for policy fail-modes
──────────────────────────────────────────────────────────────────

Audit defects AP-1 + AP-3 (see ``docs/identity/tenant-propagation-audit.md``)
exposed that this module previously contained an AUTHORITY policy
(``TenantScopePolicy``) that ALLOWed when its allowlist was empty.
A second AUTHORITY policy in another substrate
(``app.coordination.policy.evaluators.builtin.TenantIsolationEvaluator``)
already fail-closed when its tenant was missing — the two systems
carried divergent doctrines for the same constitutional class.

The unified doctrine, enforced by this module from Wedge B5 onward:

**AUTHORITY policies** — policies that GATE operations against an
allowlist or a required identity — MUST FAIL CLOSED on indeterminate
configuration. An unconfigured allowlist is NOT consent to be
permissive; it is an admission that the policy cannot decide. The
constitutional class that includes:

  * ``TenantScopePolicy``                       (this module)
  * ``MaxQueryLengthPolicy.query_missing``      (this module, Phase 0)
  * ``TenantIsolationEvaluator``                (coordination policy)
  * ``build_decision`` empty-evaluations branch (Phase 0 Cluster F)

ALL share the same rule: when the AUTHORITY axis is missing or the
configuration is indeterminate, the result is ``Decision.DENY``.
Operators who legitimately do NOT want tenant scoping MUST omit the
policy from their chain entirely — explicit non-registration is the
only way to opt out. Registering ``TenantScopePolicy()`` with no
allowlist is now a configuration error, signalled by a DENY at
evaluation time.

**CONTENT policies** — policies that FILTER or REDACT content
against a denylist — MAY remain permissive on empty configuration
because their action shape is "filter, not gate". An empty denylist
genuinely means "nothing to redact" and producing ALLOW is the
correct verdict. The class includes:

  * ``ContentDenylistPolicy`` (this module)

This taxonomy is the contract every future builtin policy MUST
declare against: a policy must self-classify as AUTHORITY or CONTENT
in its own docstring and select its empty-config behaviour
accordingly.
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
    """AUTHORITY-class policy. DENY when the subject's ``tenant_id``
    is not in ``allowed_tenants``.

    Constitutional class: AUTHORITY (gates operations against an
    allowlist). Per the module doctrine, this policy FAILS CLOSED on
    every indeterminate input:

      * empty allowlist            → DENY (``tenant_scope_unconfigured``)
      * missing ``tenant_id``       → DENY (``tenant_missing``)
      * ``tenant_id`` not in allowlist → DENY (``tenant_not_allowed``)

    Deployments that legitimately do not want tenant scoping MUST
    omit the policy from their chain entirely — registering an
    unconfigured ``TenantScopePolicy()`` is a configuration error
    and the policy will refuse to allow anything until an allowlist
    is supplied. This closes audit defect AP-1 (Wedge B1) and
    unifies the policy's empty-config doctrine with
    ``TenantIsolationEvaluator`` and ``MaxQueryLengthPolicy``
    (audit defect AP-3 → Wedge B5).

    Reads ``tenant_id`` from the typed subject (Retrieval or
    Execution). For other subject kinds the policy falls back to
    ``context.tenant_id``, which since Wedge B7 is itself the
    output of ``resolve_authority`` (singular, attributed, no silent
    coalescing).
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
        # Wedge B5 — closes audit defect AP-1 (governance fail-open).
        # An empty allowlist is NOT operator consent to be
        # permissive; it is an indeterminate configuration. Per the
        # AUTHORITY-class doctrine declared at the top of this
        # module, AUTHORITY policies fail closed on indeterminate
        # configuration. Operators who legitimately do not want
        # tenant scoping MUST omit the policy from their chain
        # rather than registering it with no allowlist.
        if not self.allowed_tenants:
            return (
                PolicyEvaluationResult(
                    policy_name=self.name,
                    rule_id="tenant_scope_unconfigured",
                    decision=Decision.DENY,
                    severity=ViolationSeverity.HIGH,
                    reason=(
                        "tenant_scope policy has no allowlist "
                        "configured; AUTHORITY-class policies fail "
                        "closed on indeterminate configuration. "
                        "Omit this policy from the chain to opt out "
                        "of tenant scoping."
                    ),
                    metadata={
                        "config_missing": "allowed_tenants",
                        "fail_mode": "closed",
                        "policy_class": "authority",
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
    """AUTHORITY-class policy. DENY when the retrieval subject's
    ``query`` exceeds ``max_length`` OR is missing.

    Constitutional class: AUTHORITY (gates retrieval against a
    declared upper bound). Per the module doctrine, this policy
    FAILS CLOSED on every indeterminate input — both ``query_missing``
    and ``query_too_long`` produce DENY. The ``query_missing`` rule
    was the original Phase 0 Cluster F symmetry anchor for the
    unified AUTHORITY fail-closed doctrine that Wedge B5 extends
    to ``TenantScopePolicy``.

    Reads ``subject.query`` directly — typed access, no dict
    lookups. The policy is RETRIEVAL-only by
    ``applicable_subject_kinds``; the engine skips it for any other
    subject kind.
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
    """CONTENT-class policy. REDACT individual retrieval candidates
    with denylisted content.

    Constitutional class: CONTENT (filters/redacts content against a
    denylist). Per the module doctrine, CONTENT-class policies MAY
    remain permissive on empty configuration because their action
    shape is "filter, not gate". An empty denylist genuinely means
    "no content rules to apply" and producing ALLOW is the correct
    verdict — this is NOT the same constitutional class as the
    AUTHORITY-class fail-closed sites (``TenantScopePolicy``,
    ``MaxQueryLengthPolicy.query_missing``).

    Operationally this is the **contract** — emitting REDACT plus
    matching restrictions. The actual filtering happens in the
    ``RedactionGuardrail`` (separation: policies emit verdicts;
    guardrails act). This separation matters because the same REDACT
    decision can be enforced differently depending on transport.

    The policy reads ``subject.retrieval_candidates`` (a tuple of
    ``CandidateSummary``) directly. Empty candidates → ALLOW;
    non-empty candidates → one REDACT per match plus a single ALLOW
    fallback if nothing matched.
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

"""`TenantIsolationEvaluator` — cross-tenant boundary policing.

The evaluator inspects the sender / recipient tenant identifiers
attached to a `CoordinationPolicyEvaluationRequest` and emits
findings when the topology crosses a tenant boundary OR when a
required tenant is absent.

Three behaviours, all advisory (Rule 3 — no orchestration mutation):

1. **Missing tenant** — when `require_tenant=True` and the request
   does not carry a `tenant_id`, the evaluator emits a DENY finding
   (cross-tenant policing cannot run without a tenant).
2. **Cross-tenant** — when `sender_tenant_id` != `recipient_tenant_id`
   and the pair is NOT on the `allowed_cross_tenant_pairs` allowlist,
   the evaluator emits a DENY finding.
3. **Authorised cross-tenant** — when the pair IS on the allowlist,
   the evaluator emits an ANNOTATE finding so the audit trail
   records the cross-tenant operation.

The evaluator is intentionally policy-free at the rule level — its
configuration is the allowlist and the require-tenant flag.
Deployments that want tenant-specific declarative rules can wire
additional `CoordinationPolicy`s into the `TopologyEvaluator`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import ClassVar

from app.coordination.policy.contracts.requests import (
    CoordinationPolicyEvaluationRequest,
)
from app.coordination.policy.enums import (
    CoordinationPolicyDecision,
    CoordinationPolicyScope,
)
from app.coordination.policy.evaluators.base import (
    BaseCoordinationPolicyEvaluator,
)
from app.coordination.policy.identity import derive_finding_id
from app.coordination.policy.models.findings import (
    CoordinationPolicyFinding,
)
from app.coordination.policy.taxonomy import (
    CoordinationPolicyFindingCode,
)


class TenantIsolationEvaluator(BaseCoordinationPolicyEvaluator):
    """Cross-tenant boundary evaluator.

    Configuration:

        allowed_cross_tenant_pairs:
            Iterable of ``(sender_tenant, recipient_tenant)`` tuples
            that are explicitly permitted to cross tenant boundaries.
            Order matters: ``(A, B)`` allows A→B but NOT B→A.
        require_tenant:
            When True, a request that carries no `tenant_id` is
            denied (defaults to True — strict isolation default).
    """

    name: ClassVar[str] = "tenant_isolation"

    def __init__(
        self,
        *,
        allowed_cross_tenant_pairs: tuple[tuple[str, str], ...] = (),
        require_tenant: bool = True,
    ) -> None:
        # Store as a frozenset for O(1) membership; order is preserved
        # in `allowed_cross_tenant_pairs` for `__repr__` / audit
        # introspection.
        self._allowed_pairs: frozenset[tuple[str, str]] = frozenset(
            allowed_cross_tenant_pairs
        )
        self._allowed_pairs_ordered: tuple[tuple[str, str], ...] = tuple(
            allowed_cross_tenant_pairs
        )
        self._require_tenant: bool = require_tenant

    @property
    def allowed_cross_tenant_pairs(self) -> tuple[tuple[str, str], ...]:
        return self._allowed_pairs_ordered

    @property
    def require_tenant(self) -> bool:
        return self._require_tenant

    async def evaluate(
        self, request: CoordinationPolicyEvaluationRequest
    ) -> tuple[CoordinationPolicyFinding, ...]:
        findings: list[CoordinationPolicyFinding] = []

        # 1. Missing-tenant check.
        if self._require_tenant and request.tenant_id is None:
            findings.append(
                self._finding(
                    request=request,
                    decision=CoordinationPolicyDecision.DENY,
                    code=CoordinationPolicyFindingCode.TENANT_ISOLATION_MISSING_TENANT,
                    message=(
                        "tenant_isolation requires a tenant_id; "
                        "request carries none"
                    ),
                    ordinal=len(findings),
                )
            )
            return tuple(findings)

        # 2. Cross-tenant check.
        sender_tenant = request.sender_tenant_id
        recipient_tenant = request.recipient_tenant_id
        if (
            sender_tenant is not None
            and recipient_tenant is not None
            and sender_tenant != recipient_tenant
        ):
            pair = (sender_tenant, recipient_tenant)
            if pair in self._allowed_pairs:
                findings.append(
                    self._finding(
                        request=request,
                        decision=CoordinationPolicyDecision.ANNOTATE,
                        code=CoordinationPolicyFindingCode.TENANT_ISOLATION_CROSS_TENANT,
                        message=(
                            f"cross-tenant operation authorised "
                            f"{sender_tenant!r} → {recipient_tenant!r}"
                        ),
                        ordinal=len(findings),
                    )
                )
            else:
                findings.append(
                    self._finding(
                        request=request,
                        decision=CoordinationPolicyDecision.DENY,
                        code=CoordinationPolicyFindingCode.TENANT_ISOLATION_VIOLATION,
                        message=(
                            f"cross-tenant operation not authorised "
                            f"{sender_tenant!r} → {recipient_tenant!r}"
                        ),
                        ordinal=len(findings),
                    )
                )

        return tuple(findings)

    # ─── Internals ───────────────────────────────────────────────────

    @staticmethod
    def _finding(
        *,
        request: CoordinationPolicyEvaluationRequest,
        decision: CoordinationPolicyDecision,
        code: CoordinationPolicyFindingCode,
        message: str,
        ordinal: int,
    ) -> CoordinationPolicyFinding:
        seed_uuid = (
            request.evaluation_id_override
            if request.evaluation_id_override is not None
            else request.coordination_id
        )
        finding_id = derive_finding_id(
            evaluation_id=seed_uuid,
            evaluator_name=TenantIsolationEvaluator.name,
            code=str(code),
            ordinal=ordinal,
        )
        return CoordinationPolicyFinding(
            finding_id=finding_id,
            evaluator_name=TenantIsolationEvaluator.name,
            scope=CoordinationPolicyScope.TENANT,
            decision=decision,
            code=str(code),
            message=message,
            detected_at=datetime.now(timezone.utc),
        )


__all__ = ["TenantIsolationEvaluator"]

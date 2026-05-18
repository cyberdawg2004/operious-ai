"""`ArbitrationRequest` — typed input to `evaluate()`.

The request wraps an immutable `ArbitrationCase` and adds the
per-call identifiers / overrides:

* `evaluator_names` — optional whitelist; ``None`` runs every
                       registered evaluator.
* `evaluation_id_override` — replay aid (caller-pinned id).
* `correlation_id`, `request_id`, `tenant_id` — lineage continuity.
* `metadata` — free-form, propagated onto trace + result.

Replay-safety: identical inputs (including
`evaluation_id_override`) produce an identical
`ArbitrationResult` modulo wall-clock fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from app.arbitration.identity import ArbitrationEvaluationId
from app.arbitration.models.case import ArbitrationCase
from app.identity import (
    AuthorityContext,
    check_tenant_authority_coexistence,
)


@dataclass(frozen=True, slots=True)
class ArbitrationRequest:
    """Input to one `OperationalArbitrationRuntime.evaluate()` call.

    ``authority`` carries the typed :class:`AuthorityContext`
    (Wedge B2 typed-ingress surface). When both ``authority`` and
    ``tenant_id`` are supplied, they MUST agree (Branch A
    coexistence invariant).
    """

    case: ArbitrationCase
    correlation_id: str | None = None
    request_id: str | None = None
    tenant_id: str | None = None
    evaluator_names: tuple[str, ...] | None = None
    evaluation_id_override: ArbitrationEvaluationId | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    authority: AuthorityContext | None = None

    def __post_init__(self) -> None:
        check_tenant_authority_coexistence(
            contract_name="ArbitrationRequest",
            authority=self.authority,
            tenant_id=self.tenant_id,
        )


__all__ = ["ArbitrationRequest"]

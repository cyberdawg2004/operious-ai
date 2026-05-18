"""`CoordinationDispatchRequest` — input to `CoordinationRuntime.dispatch()`.

The request carries:

* the typed `CoordinationMessage` (sender, recipient, payload, type),
* the operational `direction` classification,
* lineage handles (correlation id, parent dispatch / message ids),
* a replay aid (`coordination_id_override`),
* a governance-context customisation hook (`enforcement_stage`,
  optional override of governance metadata).

The request is replay-safe: passing identical inputs (including the
optional `coordination_id_override`) produces an identical
`CoordinationDispatchResult` modulo wall-clock fields on the trace.

Governance composition note:

The runtime ALWAYS invokes governance for every dispatch. By default
the runtime builds the `GovernanceContext` from the message fields
(action ← message_type → `CoordinationGovernanceAction`, resource ←
recipient identity, actor ← sender). Callers may pin
`enforcement_stage` to direct which policy chain applies; the
default is `EnforcementStage.PRE_EXECUTION` because coordination
dispatch precedes the recipient's execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from app.coordination.contracts.messages import CoordinationMessage
from app.coordination.enums import CoordinationDirection
from app.coordination.identity import (
    CoordinationCorrelationId,
    CoordinationId,
    CoordinationMessageId,
)
from app.governance.enums import EnforcementStage
from app.identity import AuthorityContext


@dataclass(frozen=True, slots=True)
class CoordinationDispatchRequest:
    """Input to one coordination dispatch.

    Attributes:
        message:                 The `CoordinationMessage` being
                                  dispatched.
        direction:               Operational direction classification.
                                  Recorded on the envelope and
                                  surfaced into governance metadata;
                                  does NOT alter dispatch semantics.
        correlation_id:          Optional pipeline-level grouping.
                                  Threads into governance and into
                                  the persisted envelope.
        parent_coordination_id:  Optional id of the dispatch that
                                  CAUSED this one. Causality at the
                                  dispatch level.
        parent_message_id:       Optional id of the message that
                                  CAUSED this one. Causality at the
                                  message level (independent of
                                  parent_coordination_id so a fresh
                                  dispatch can still record the
                                  message ancestor).
        request_id:              Platform-wide request id. Sourced
                                  from `app.observability.context` if
                                  the caller does not supply one.
        tenant_id:               Tenant scope. If supplied, overrides
                                  the recipient's tenant on the
                                  envelope and governance context;
                                  callers SHOULD supply the same
                                  value the surrounding governance
                                  pipeline uses.
        authority:               Typed authority tuple (Wedge B2).
                                  When supplied with a non-None
                                  ``tenant_id`` axis, becomes the
                                  canonical authority source — see
                                  ``resolve_authority`` in
                                  ``app.identity``. When both
                                  ``authority`` and ``tenant_id``
                                  are supplied with values, they
                                  MUST agree (Wedge B7 coexistence
                                  invariant).
        enforcement_stage:       Which governance stage chain to run.
                                  Defaults to `PRE_EXECUTION`.
        coordination_id_override:
                                  Replay aid. When ``None`` the
                                  runtime mints a fresh
                                  `CoordinationId`.
        chain_depth:             Coordination chain depth for this
                                  dispatch. Sprint L3
                                  recursive-delegation protection:
                                  top-level dispatches MUST report
                                  ``0``; child dispatches MUST report
                                  ``parent.chain_depth + 1``. The
                                  topology substrate trusts the
                                  caller's value (does not walk
                                  persistence in the hot path); the
                                  `ChainDepthEvaluator` compares
                                  against `topology.max_chain_depth`.
        governance_metadata:     Extra metadata merged into the
                                  `GovernanceContext.metadata` the
                                  runtime constructs. Substrate keys
                                  (``coordination.*``) always win;
                                  the override is for caller-specific
                                  audit fields.
        metadata:                Free-form, propagated onto the trace
                                  and envelope verbatim.
    """

    message: CoordinationMessage
    direction: CoordinationDirection
    correlation_id: CoordinationCorrelationId | None = None
    parent_coordination_id: CoordinationId | None = None
    parent_message_id: CoordinationMessageId | None = None
    request_id: str | None = None
    tenant_id: str | None = None
    authority: AuthorityContext | None = None
    enforcement_stage: EnforcementStage = EnforcementStage.PRE_EXECUTION
    coordination_id_override: CoordinationId | None = None
    chain_depth: int = 0
    governance_metadata: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Wedge B7 coexistence invariant (mirrored from boundary +
        # supervisor contracts): when both the typed ``authority``
        # and the legacy ``tenant_id`` are supplied with values,
        # they MUST agree. ``None`` on either side is permitted —
        # legacy callers (tenant_id only) and typed callers
        # (authority only) are both supported during the typed-
        # ingress transition.
        if (
            self.authority is not None
            and self.authority.tenant_id is not None
            and self.tenant_id is not None
            and self.authority.tenant_id != self.tenant_id
        ):
            raise ValueError(
                "CoordinationDispatchRequest: authority.tenant_id "
                "and tenant_id must agree when both are supplied "
                f"(got authority.tenant_id="
                f"{self.authority.tenant_id!r}, "
                f"tenant_id={self.tenant_id!r})"
            )


__all__ = ["CoordinationDispatchRequest"]

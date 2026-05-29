"""`ExecutionInspectionRequest` — typed input to `SupervisorRuntime.inspect()`.

Carries either a live `AgentExecutionEnvelope` or replay records; the
runtime normalises both into an `InspectionView` before evaluators
run.

The request is replay-safe: passing identical inputs (including the
optional `inspection_id_override`) produces an identical
`ExecutionInspectionResult` modulo wall-clock fields on the trace.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from app.agents.envelopes import AgentExecutionEnvelope
from app.agents.persistence.records import (
    AgentExecutionRecord,
    ToolInvocationRecord,
)
from app.governance.persistence.records import GovernanceDecisionRecord
from app.identity import (
    AuthorityContext,
    check_tenant_authority_coexistence,
)


@dataclass(frozen=True, slots=True)
class ExecutionInspectionRequest:
    """Input to one supervisor inspection.

    Exactly ONE inspection source must be populated:

    * `live_envelope`              — for post-execution inspection
                                     against the freshly-produced
                                     envelope, OR
    * the trio (`recorded_execution`, `recorded_tool_invocations`,
      `recorded_governance_decisions`) — for replay inspection
                                     against records loaded from
                                     storage.

    The runtime raises `InspectionRequestError` if both or neither
    are present. Both supplied is ambiguous; neither is impossible.

    Attributes:
        execution_id:               The execution being inspected.
                                     For live mode this MUST match
                                     `live_envelope.trace.execution_id`.
        correlation_id / request_id / tenant_id:
                                     Carried through onto the
                                     inspection result + trace.
        authority:                   Typed authority tuple (Wedge B2).
                                     When supplied with a non-None
                                     ``tenant_id`` axis, becomes the
                                     canonical authority source — see
                                     ``resolve_authority`` in
                                     ``app.identity``. When both
                                     ``authority`` and ``tenant_id``
                                     are supplied with values, they
                                     MUST agree.
        evaluator_names:             Optional whitelist; when ``None``
                                     every registered evaluator runs.
                                     When provided, evaluators are
                                     run in sorted-name order over
                                     the intersection of the
                                     whitelist and the registry.
        inspection_id_override:      Replay aid; when ``None`` the
                                     runtime mints `uuid4`.
        decision_id_override:        Replay aid for the supervisor's
                                     `SupervisorDecision.decision_id`.
        metadata:                    Free-form, propagated onto the
                                     trace + result.
    """

    execution_id: uuid.UUID
    correlation_id: uuid.UUID | None = None
    request_id: str | None = None
    tenant_id: str | None = None
    authority: AuthorityContext | None = None
    live_envelope: AgentExecutionEnvelope | None = None
    recorded_execution: AgentExecutionRecord | None = None
    recorded_tool_invocations: tuple[ToolInvocationRecord, ...] = ()
    recorded_governance_decisions: tuple[GovernanceDecisionRecord, ...] = ()
    evaluator_names: tuple[str, ...] | None = None
    inspection_id_override: uuid.UUID | None = None
    decision_id_override: uuid.UUID | None = None
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])

    def __post_init__(self) -> None:
        check_tenant_authority_coexistence(
            contract_name="ExecutionInspectionRequest",
            authority=self.authority,
            tenant_id=self.tenant_id,
        )


__all__ = ["ExecutionInspectionRequest"]

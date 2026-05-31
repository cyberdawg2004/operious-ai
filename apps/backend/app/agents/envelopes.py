"""Agent runtime envelopes.

Same discipline as every other envelope in the platform: one envelope
per public-API call, the trace is always present, the result is
present iff successful, the error is present iff failed.

The substrate APIs that produce envelopes (`AgentRuntime.execute`,
`ToolInvoker.invoke`, `AgentToolSession.invoke`) **never raise** —
every failure mode lands on the envelope.

`AgentExecutionEnvelope` aggregates the per-execution view: the
agent's own result, every tool-invocation envelope produced under it,
and every governance envelope touched. Replay tools reconstruct the
full execution from this object.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.agents.enums import ExecutionState, ToolInvocationStatus
from app.agents.results import AgentExecutionResult, ToolInvocationResult
from app.agents.tracing import AgentExecutionTrace, ToolInvocationTrace
from app.governance.envelopes import GovernanceEnvelope


@dataclass(frozen=True, slots=True)
class ToolInvocationEnvelope:
    """Never-raising container for one tool invocation outcome.

    ``provider_idempotency_key`` is the deterministic key a durable
    pre-approved action grant carries to downstream provider integrations.
    Retries of the same logical grant expose the same value, so future
    provider adapters can forward it without re-deriving action identity.
    """

    trace: ToolInvocationTrace
    result: ToolInvocationResult | None = None
    error: BaseException | None = None
    governance_envelope: GovernanceEnvelope | None = None
    provider_idempotency_key: str | None = None

    @property
    def is_ok(self) -> bool:
        """True iff the tool actually executed without error.

        Denied invocations return ``False`` here — the substrate
        succeeded at *deciding* to deny, but no tool ran.
        """
        return (
            self.error is None
            and self.result is not None
            and self.trace.status is ToolInvocationStatus.OK
        )

    @property
    def is_denied(self) -> bool:
        """True iff a governance / constraint denied the call."""
        return self.trace.status is ToolInvocationStatus.DENIED


@dataclass(frozen=True, slots=True)
class AgentExecutionEnvelope:
    """Never-raising container for one agent execution outcome.

    Attributes:
        trace:                Always present.
        result:               Present iff `final_state` is COMPLETED.
        error:                Present iff `final_state` is FAILED or
                              CANCELLED-with-error.
        tool_envelopes:       Every tool envelope produced under this
                              execution, in invocation order.
        governance_envelopes: Every governance envelope produced under
                              this execution, in invocation order.
    """

    trace: AgentExecutionTrace
    result: AgentExecutionResult | None = None
    error: BaseException | None = None
    tool_envelopes: tuple[ToolInvocationEnvelope, ...] = field(default_factory=tuple)
    governance_envelopes: tuple[GovernanceEnvelope, ...] = field(default_factory=tuple)

    @property
    def is_ok(self) -> bool:
        """True iff execution reached COMPLETED with a result."""
        return (
            self.error is None
            and self.result is not None
            and self.trace.final_state is ExecutionState.COMPLETED
        )


__all__ = [
    "ToolInvocationEnvelope",
    "AgentExecutionEnvelope",
]

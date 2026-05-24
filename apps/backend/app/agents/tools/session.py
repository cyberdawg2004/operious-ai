"""Per-execution tool-invocation session.

`AgentToolSession` is the **only** API agents see for invoking
tools. The runtime constructs one per `execute()` call, scoped to a
single `AgentExecutionContext`. The session:

* enforces `max_tool_invocations` (substrate-side cap, before the
  invoker even runs),
* delegates to the underlying `ToolInvoker` (which does the rest:
  capability + constraint + governance),
* captures every produced envelope so the runtime can fold them into
  the `AgentExecutionEnvelope`.

Why a session and not a per-call new invoker: the invoker is
configured once at composition time (DI) — same registries, same
governance runtime. The session adds the per-execution state
(envelope buffer, invocation count) without forcing the invoker to
become stateful.

The session is single-coroutine — no thread-safety guarantees. An
agent that wants concurrent tool calls within one execution should
gather the results explicitly; the session itself preserves
invocation order.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.agents.context import AgentExecutionContext
from app.agents.envelopes import ToolInvocationEnvelope
from app.agents.enums import ToolInvocationStatus
from app.agents.exceptions import ConstraintViolationError
from app.agents.identity import derive_tool_invocation_id
from app.agents.results import ToolInvocationRequest
from app.agents.tools.invoker import ToolInvoker
from app.agents.tracing import ToolInvocationTrace


class AgentToolSession:
    """Per-execution tool-invocation API handed to agents."""

    def __init__(
        self,
        *,
        invoker: ToolInvoker,
        context: AgentExecutionContext,
    ) -> None:
        self._invoker = invoker
        self._context = context
        self._envelopes: list[ToolInvocationEnvelope] = []

    async def invoke(
        self, request: ToolInvocationRequest
    ) -> ToolInvocationEnvelope:
        """Invoke a tool through the substrate. Never raises."""
        cap = self._context.constraints.max_tool_invocations
        if cap and len(self._envelopes) >= cap:
            envelope = self._cap_exceeded_envelope(request, cap)
            self._envelopes.append(envelope)
            return envelope
        envelope = await self._invoker.invoke(
            request,
            self._context,
            invocation_ordinal=len(self._envelopes) + 1,
        )
        self._envelopes.append(envelope)
        return envelope

    @property
    def envelopes(self) -> tuple[ToolInvocationEnvelope, ...]:
        """Every envelope produced under this session, in order."""
        return tuple(self._envelopes)

    @property
    def invocation_count(self) -> int:
        return len(self._envelopes)

    # ─── Internals ────────────────────────────────────────────────────

    def _cap_exceeded_envelope(
        self,
        request: ToolInvocationRequest,
        cap: int,
    ) -> ToolInvocationEnvelope:
        loop = asyncio.get_event_loop()
        started_at = datetime.now(timezone.utc)
        loop_start = loop.time()
        ended_at = datetime.now(timezone.utc)
        latency_ms = round((loop.time() - loop_start) * 1000, 2)
        error = ConstraintViolationError(
            f"max_tool_invocations cap exceeded: {cap}"
        )
        trace = ToolInvocationTrace(
            invocation_id=derive_tool_invocation_id(
                execution_id=self._context.execution.execution_id,
                tool_name=request.tool_name,
                invocation_ordinal=len(self._envelopes) + 1,
                payload=request.payload,
                metadata=request.metadata,
            ),
            execution_id=self._context.execution.execution_id,
            tool_name=request.tool_name,
            status=ToolInvocationStatus.DENIED,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            error=f"{type(error).__name__}: {error}",
            metadata={"reason": "max_invocations_exceeded", "cap": cap},
        )
        return ToolInvocationEnvelope(
            trace=trace,
            error=error,
        )


__all__ = ["AgentToolSession"]

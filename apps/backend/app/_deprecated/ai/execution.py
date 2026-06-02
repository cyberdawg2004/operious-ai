"""Per-call execution context.

Separates *how* an inference is dispatched (which provider, under which
request id, with what metadata) from *what* is being inferred
(`InferenceRequest`). Keeping the two apart means we can:

* re-run the same `InferenceRequest` against a different provider for
  comparison / failover, without rebuilding the payload,
* attach orchestration metadata (agent step id, workflow run id) to
  the trace without polluting the inference contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    """Per-call dispatch options.

    Attributes:
        provider:   Override the gateway's default provider name. None
                    means "use the configured default".
        request_id: Override the ambient request id (from middleware).
                    Most callers leave this `None` and let the gateway
                    read the ContextVar.
        metadata:   Free-form, propagated into the trace. Use for agent
                    step ids, workflow run ids, tenant tags, etc.
    """

    provider: str | None = None
    request_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])


__all__ = ["ExecutionContext"]

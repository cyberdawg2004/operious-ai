"""Per-call embedding execution context.

Separates *how* an embedding call is dispatched (which provider, under
which request id, with what metadata) from *what* is being embedded
(`EmbeddingRequest.texts`). This lets us re-execute the same request
through a different provider for comparison / failover without
rebuilding the payload.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class EmbeddingExecutionContext:
    """Per-call embedding dispatch options.

    Attributes:
        provider:   Override the gateway's default provider name. None
                    means "use the configured default".
        request_id: Override the ambient request id. Most callers leave
                    this `None` so the gateway reads the ContextVar.
        metadata:   Free-form; propagated into the trace + audit event.
    """

    provider: str | None = None
    request_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])


__all__ = ["EmbeddingExecutionContext"]

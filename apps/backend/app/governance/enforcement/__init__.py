"""Enforcement runtime and handlers.

A `GovernanceDecision` is just data. The enforcement layer is the
*action*: given a decision, what does the runtime DO?

Components:

* `models`     — `EnforcementAction`, `EnforcementOutcome`. Frozen
                 records of what a handler did.
* `handlers`   — `BaseEnforcementHandler` + one builtin per
                 `Decision` value (`AllowHandler`, `DenyHandler`,
                 `RedactHandler`, `DegradeHandler`, `EscalateHandler`,
                 `RequireApprovalHandler`).
* `runtime`    — `GovernanceRuntime`, the apex orchestrator. Composes
                 the engine, the chain registry, the handler registry,
                 and the observability seam. Produces one
                 `GovernanceEnvelope` per call.

Architectural rules:

* handlers MAY perform I/O when their decision class demands it
  (e.g., enqueueing an approval request) but Sprint I ships
  side-effect-free reference handlers,
* handlers MUST be deterministic in the metadata they emit,
* the runtime never raises — every error lands on the envelope.
"""

from app.governance.enforcement.handlers import (
    AllowHandler,
    BaseEnforcementHandler,
    DegradeHandler,
    DenyHandler,
    EnforcementHandlerRegistry,
    EscalateHandler,
    RedactHandler,
    RequireApprovalHandler,
)
from app.governance.enforcement.models import (
    EnforcementAction,
    EnforcementOutcome,
)
from app.governance.enforcement.runtime import GovernanceRuntime

__all__ = [
    "BaseEnforcementHandler",
    "AllowHandler",
    "DenyHandler",
    "RedactHandler",
    "DegradeHandler",
    "EscalateHandler",
    "RequireApprovalHandler",
    "EnforcementHandlerRegistry",
    "EnforcementAction",
    "EnforcementOutcome",
    "GovernanceRuntime",
]

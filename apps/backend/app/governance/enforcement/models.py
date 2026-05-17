"""Enforcement-action data shapes.

A handler executes a decision and returns one `EnforcementAction` —
the durable record of *what the handler did* in response to the
decision. The action is what the runtime puts on the trace and what
supervisor runtimes read to reconstruct enforcement lineage.

`EnforcementOutcome` is a small enum capturing whether the handler's
action completed normally or hit an error path.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping


class EnforcementOutcome(StrEnum):
    """What happened when the handler applied the decision."""

    APPLIED = "applied"          # Handler ran cleanly.
    NO_OP = "no_op"              # Decision did not require action (ALLOW).
    DEFERRED = "deferred"        # Action queued / awaiting external resolution.
    FAILED = "failed"            # Handler raised; runtime folds into envelope.


@dataclass(frozen=True, slots=True)
class EnforcementAction:
    """Durable record of one handler execution."""

    action_id: uuid.UUID
    handler_name: str
    decision_id: uuid.UUID
    outcome: EnforcementOutcome
    applied_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    detail: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)


__all__ = ["EnforcementOutcome", "EnforcementAction"]

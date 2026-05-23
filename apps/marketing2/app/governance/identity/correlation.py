"""Correlation primitives.

A single operational pipeline (e.g. one `GovernedAssemblyRuntime.assemble()`
call) performs multiple governance evaluations — PRE_RETRIEVAL,
PRE_EXECUTION, and eventually POST_RETRIEVAL / PRE_GROUNDING /
POST_EXECUTION as those hooks land. Each evaluation produces its own
`decision_id`; they share a `correlation_id` so persistence and
supervisor runtimes can reconstruct the full pipeline lineage.

Two shapes here:

* `CorrelationContext` — what callers PASS IN. Holds the
  `correlation_id` + `request_id`. The composition layer
  (`GovernedAssemblyRuntime`) constructs one of these once per
  pipeline invocation and threads it through every governance
  context.

* `CorrelationKey` — what supervisor / audit consumers READ OUT.
  Holds the identity triple (`correlation_id`, `decision_id`,
  `enforcement_action_ids`) that lets queries reconstruct
  decision-to-enforcement lineage.

Both are immutable, hashable, replay-safe.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class CorrelationContext:
    """Lineage identifiers for one operational pipeline.

    Carried THROUGH `GovernanceContext.correlation_id` into every
    governance evaluation performed under the pipeline. The same
    `correlation_id` appears on every produced `GovernanceTrace`,
    enabling pipeline-level queries.

    Attributes:
        correlation_id: Stable UUID identifying the pipeline.
        request_id:     Platform-wide request id (when known).
    """

    correlation_id: uuid.UUID
    request_id: str | None = None


@dataclass(frozen=True, slots=True)
class CorrelationKey:
    """Read-out shape for the decision-to-enforcement identity triple.

    Used by persistence layers and supervisor runtimes to express
    "this is the full identity context for one decision + its
    enforcement actions".

    Attributes:
        decision_id:             The decision this key identifies.
        correlation_id:          The pipeline this decision belongs to
                                 (when one is configured).
        request_id:              The platform-wide request id.
        enforcement_action_ids:  IDs of every `EnforcementAction`
                                 produced for this decision (may be
                                 empty for ALLOW outcomes).
    """

    decision_id: uuid.UUID
    correlation_id: uuid.UUID | None = None
    request_id: str | None = None
    enforcement_action_ids: tuple[uuid.UUID, ...] = field(default_factory=tuple)


__all__ = ["CorrelationContext", "CorrelationKey"]

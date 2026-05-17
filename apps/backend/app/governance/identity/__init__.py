"""Governance identity layer.

This package defines the **canonical identity primitives** for the
governance substrate:

* `decision_ids`  — `generate_decision_id`, `derive_decision_id`,
                    `DECISION_NAMESPACE`.
* `trace_ids`     — `generate_trace_id`, `derive_trace_id`,
                    `TRACE_NAMESPACE`.
* `correlation`   — `CorrelationContext`, `CorrelationKey`, helpers
                    to inspect identity relationships across decisions,
                    traces, and enforcement actions.

Identity semantics (see also `docs/architecture/governance-replay-semantics.md`):

* **Runtime path** — every `generate_*_id()` returns a UUID4. IDs
  are unique across live runtime execution; no two evaluations
  produce the same `decision_id`.
* **Replay / deterministic path** — every `derive_*_id(seed=...)`
  returns a UUID5 keyed against the package's namespace. Same seed
  → same UUID. Replay tools that need byte-identical reconstruction
  use this path; production runtime does NOT.
* **Honest contract** — replay preserves **lineage relationships**
  (which decision belongs to which correlation, which enforcement
  action belongs to which decision), NOT byte-identical UUID
  reproduction. The substrate is explicit about this — fields other
  than IDs (decision, evaluated_rules, etc.) ARE deterministic, so
  a replay produces the same VERDICT for the same INPUTS even when
  the `decision_id` differs.
"""

from app.governance.identity.correlation import (
    CorrelationContext,
    CorrelationKey,
)
from app.governance.identity.decision_ids import (
    DECISION_NAMESPACE,
    derive_decision_id,
    generate_decision_id,
)
from app.governance.identity.trace_ids import (
    TRACE_NAMESPACE,
    derive_trace_id,
    generate_trace_id,
)

__all__ = [
    "DECISION_NAMESPACE",
    "generate_decision_id",
    "derive_decision_id",
    "TRACE_NAMESPACE",
    "generate_trace_id",
    "derive_trace_id",
    "CorrelationContext",
    "CorrelationKey",
]

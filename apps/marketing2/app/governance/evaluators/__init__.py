"""Policy evaluation engine.

The engine is the **single** place that calls into policies. Its job:

1. Run every policy in a chain *in declared order* against one
   `GovernanceContext`.
2. Collect every `PolicyEvaluationResult` they produce.
3. Catch any raised `Exception` from a misbehaving policy and replace
   it with a **synthetic DENY result** so the substrate is fail-safe
   by construction.
4. Emit per-policy traces (one per invocation, success or failure).
5. Hand the result tuple + the policy traces to the runtime, which
   builds the final `GovernanceDecision` and the `GovernanceEnvelope`.

The engine never logs / never emits metrics — that responsibility
lives on the runtime. The engine is a *pure-ish* coordinator: same
chain + same context + same wall-clock-independent policy logic
yields the same output (modulo trace timestamps).
"""

from app.governance.evaluators.engine import (
    EngineEvaluationResult,
    PolicyEvaluationEngine,
)

__all__ = [
    "EngineEvaluationResult",
    "PolicyEvaluationEngine",
]

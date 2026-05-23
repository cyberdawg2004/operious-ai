"""Coordination policy identity primitives.

Three typed identifiers, mirroring the discipline of
`app/coordination/identity.py`:

* `CoordinationPolicyId`           — one per registered
                                      `CoordinationPolicy`. Stable
                                      across deployments when derived
                                      from a stable seed.
* `CoordinationPolicyEvaluationId` — one per
                                      `CoordinationPolicyRuntime.evaluate()`
                                      call. Identifies the evaluation
                                      operation + the persisted
                                      envelope.
* `CoordinationPolicyChainId`      — stable identifier of the
                                      evaluator-chain composition
                                      that produced an evaluation.
                                      Derived deterministically from
                                      the sorted evaluator-name tuple
                                      so the same chain shape always
                                      yields the same id.

Generators / derivers
─────────────────────

* `generate_*` — UUID4 runtime path (live, never colliding).
* `derive_*`   — UUID5 over a pinned namespace + seed; same seed →
                  same UUID, bit-for-bit (replay path).

The namespaces are permanent constants. Changing one is a breaking
change to every previously-derived identifier in the substrate.

Finding identity (`finding_id`) is derived per-finding via
`derive_finding_id` from `(evaluation_id, evaluator_name, code,
ordinal)` so replays produce byte-identical finding identifiers.
"""

from __future__ import annotations

import uuid
import itertools
from typing import NewType


# ─── Type aliases ────────────────────────────────────────────────────


CoordinationPolicyId = NewType("CoordinationPolicyId", uuid.UUID)
"""Stable identifier for one registered `CoordinationPolicy`."""


CoordinationPolicyEvaluationId = NewType(
    "CoordinationPolicyEvaluationId", uuid.UUID
)
"""Stable identifier for one `CoordinationPolicyRuntime.evaluate()` call."""


CoordinationPolicyChainId = NewType("CoordinationPolicyChainId", uuid.UUID)
"""Stable identifier for an evaluator-chain composition."""


# ─── Namespaces — permanent constants ────────────────────────────────


_POLICY_NAMESPACE: uuid.UUID = uuid.UUID(
    "9f1a3b2c-3d4e-5f6a-7b8c-9d0e1f2a3b4c"
)
_EVALUATION_NAMESPACE: uuid.UUID = uuid.UUID(
    "a0b1c2d3-4e5f-6071-8293-a4b5c6d7e8f9"
)
_CHAIN_NAMESPACE: uuid.UUID = uuid.UUID(
    "b1c2d3e4-5f60-7182-93a4-b5c6d7e8f901"
)
_FINDING_NAMESPACE: uuid.UUID = uuid.UUID(
    "c2d3e4f5-6071-8293-a4b5-c6d7e8f90102"
)
_RUNTIME_COUNTER = itertools.count()


# ─── Runtime path: fresh UUID4 per call ──────────────────────────────


def generate_policy_id() -> CoordinationPolicyId:
    """Return a fresh UUID4 wrapped as `CoordinationPolicyId`."""
    return CoordinationPolicyId(uuid.uuid5(_POLICY_NAMESPACE, _runtime_seed("policy")))


def generate_evaluation_id() -> CoordinationPolicyEvaluationId:
    """Return a fresh UUID4 wrapped as `CoordinationPolicyEvaluationId`."""
    return CoordinationPolicyEvaluationId(uuid.uuid5(_EVALUATION_NAMESPACE, _runtime_seed("evaluation")))


def _runtime_seed(label: str) -> str:
    return f"runtime|{label}|{next(_RUNTIME_COUNTER)}"


# ─── Replay path: deterministic UUID5 from a stable seed ─────────────


def derive_policy_id(*, seed: str) -> CoordinationPolicyId:
    """Deterministically derive a `CoordinationPolicyId` from a seed."""
    if not seed:
        raise ValueError("derive_policy_id requires a non-empty seed")
    return CoordinationPolicyId(uuid.uuid5(_POLICY_NAMESPACE, seed))


def derive_evaluation_id(
    *, seed: str
) -> CoordinationPolicyEvaluationId:
    """Deterministically derive a `CoordinationPolicyEvaluationId`."""
    if not seed:
        raise ValueError("derive_evaluation_id requires a non-empty seed")
    return CoordinationPolicyEvaluationId(
        uuid.uuid5(_EVALUATION_NAMESPACE, seed)
    )


def derive_chain_id(
    *, evaluator_names: tuple[str, ...]
) -> CoordinationPolicyChainId:
    """Derive a deterministic chain id from sorted evaluator names.

    The same set of evaluator names (regardless of registration order)
    yields the same `CoordinationPolicyChainId`. This is the canonical
    audit handle for the chain composition that ran.
    """
    seed = "|".join(sorted(evaluator_names))
    if not seed:
        raise ValueError(
            "derive_chain_id requires at least one evaluator name"
        )
    return CoordinationPolicyChainId(uuid.uuid5(_CHAIN_NAMESPACE, seed))


def derive_finding_id(
    *,
    evaluation_id: uuid.UUID,
    evaluator_name: str,
    code: str,
    ordinal: int,
) -> uuid.UUID:
    """Derive a deterministic per-finding id.

    Two findings produced under the same `(evaluation_id,
    evaluator_name, code, ordinal)` always receive the same id;
    replays produce byte-identical finding identifiers.
    """
    seed = f"{evaluation_id}:{evaluator_name}:{code}:{ordinal}"
    return uuid.uuid5(_FINDING_NAMESPACE, seed)


# ─── Boundary coercion helpers ───────────────────────────────────────


def as_policy_id(value: uuid.UUID | str) -> CoordinationPolicyId:
    return CoordinationPolicyId(
        value if isinstance(value, uuid.UUID) else uuid.UUID(value)
    )


def as_evaluation_id(
    value: uuid.UUID | str,
) -> CoordinationPolicyEvaluationId:
    return CoordinationPolicyEvaluationId(
        value if isinstance(value, uuid.UUID) else uuid.UUID(value)
    )


def as_chain_id(value: uuid.UUID | str) -> CoordinationPolicyChainId:
    return CoordinationPolicyChainId(
        value if isinstance(value, uuid.UUID) else uuid.UUID(value)
    )


__all__ = [
    "CoordinationPolicyId",
    "CoordinationPolicyEvaluationId",
    "CoordinationPolicyChainId",
    "generate_policy_id",
    "generate_evaluation_id",
    "derive_policy_id",
    "derive_evaluation_id",
    "derive_chain_id",
    "derive_finding_id",
    "as_policy_id",
    "as_evaluation_id",
    "as_chain_id",
]

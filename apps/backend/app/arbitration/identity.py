"""Operational arbitration identity primitives.

Six typed identifiers, mirroring the discipline of every sibling
substrate (`app/coordination/policy/identity.py`,
`app/coordination/topology/identity.py`):

* `ArbitrationCaseId`             — one per submitted
                                     `ArbitrationCase`.
* `ArbitrationEvaluationId`       — one per `evaluate()` call.
* `ArbitrationChainId`            — stable identifier of the
                                     evaluator-chain composition.
* `ArbitrationSignalId`           — stable id of one signal in a
                                     case.
* `ArbitrationConflictId`         — stable id of one detected
                                     conflict.
* `ArbitrationRecommendationId`   — stable id of one recommendation.

Generators / derivers
─────────────────────

* `generate_*` — UUID4 runtime path.
* `derive_*`   — UUID5 over a pinned namespace + seed. Same seed →
                  same UUID bit-for-bit. Replay path.

Finding identity (`finding_id`) is derived per-finding via
`derive_finding_id` from `(evaluation_id, evaluator_name, code,
ordinal)` so replays produce byte-identical finding identifiers.

The namespaces are permanent constants. Changing one is a breaking
change to every previously derived identifier in the substrate.
"""

from __future__ import annotations

import uuid
from typing import NewType


# ─── Type aliases ────────────────────────────────────────────────────


ArbitrationCaseId = NewType("ArbitrationCaseId", uuid.UUID)
ArbitrationEvaluationId = NewType("ArbitrationEvaluationId", uuid.UUID)
ArbitrationChainId = NewType("ArbitrationChainId", uuid.UUID)
ArbitrationSignalId = NewType("ArbitrationSignalId", uuid.UUID)
ArbitrationConflictId = NewType("ArbitrationConflictId", uuid.UUID)
ArbitrationRecommendationId = NewType(
    "ArbitrationRecommendationId", uuid.UUID
)


# ─── Namespaces — permanent constants ────────────────────────────────


_CASE_NAMESPACE: uuid.UUID = uuid.UUID(
    "a1b2c3d4-0001-4001-8001-000000000001"
)
_EVALUATION_NAMESPACE: uuid.UUID = uuid.UUID(
    "a1b2c3d4-0002-4002-8002-000000000002"
)
_CHAIN_NAMESPACE: uuid.UUID = uuid.UUID(
    "a1b2c3d4-0003-4003-8003-000000000003"
)
_SIGNAL_NAMESPACE: uuid.UUID = uuid.UUID(
    "a1b2c3d4-0004-4004-8004-000000000004"
)
_CONFLICT_NAMESPACE: uuid.UUID = uuid.UUID(
    "a1b2c3d4-0005-4005-8005-000000000005"
)
_RECOMMENDATION_NAMESPACE: uuid.UUID = uuid.UUID(
    "a1b2c3d4-0006-4006-8006-000000000006"
)
_FINDING_NAMESPACE: uuid.UUID = uuid.UUID(
    "a1b2c3d4-0007-4007-8007-000000000007"
)
_DEADLOCK_NAMESPACE: uuid.UUID = uuid.UUID(
    "a1b2c3d4-0008-4008-8008-000000000008"
)


# ─── Runtime path: fresh UUID4 per call ──────────────────────────────


def generate_case_id() -> ArbitrationCaseId:
    return ArbitrationCaseId(uuid.uuid4())


def generate_evaluation_id() -> ArbitrationEvaluationId:
    return ArbitrationEvaluationId(uuid.uuid4())


def generate_signal_id() -> ArbitrationSignalId:
    return ArbitrationSignalId(uuid.uuid4())


def generate_conflict_id() -> ArbitrationConflictId:
    return ArbitrationConflictId(uuid.uuid4())


def generate_recommendation_id() -> ArbitrationRecommendationId:
    return ArbitrationRecommendationId(uuid.uuid4())


# ─── Replay path: deterministic UUID5 from a stable seed ─────────────


def derive_case_id(*, seed: str) -> ArbitrationCaseId:
    if not seed:
        raise ValueError("derive_case_id requires a non-empty seed")
    return ArbitrationCaseId(uuid.uuid5(_CASE_NAMESPACE, seed))


def derive_evaluation_id(*, seed: str) -> ArbitrationEvaluationId:
    if not seed:
        raise ValueError("derive_evaluation_id requires a non-empty seed")
    return ArbitrationEvaluationId(
        uuid.uuid5(_EVALUATION_NAMESPACE, seed)
    )


def derive_chain_id(
    *, evaluator_names: tuple[str, ...]
) -> ArbitrationChainId:
    """Derive a deterministic chain id from sorted evaluator names.

    Same set of evaluator names (regardless of registration order)
    yields the same chain id — the canonical audit handle for the
    chain composition that ran.
    """
    if not evaluator_names:
        raise ValueError(
            "derive_chain_id requires at least one evaluator name"
        )
    seed = "|".join(sorted(evaluator_names))
    return ArbitrationChainId(uuid.uuid5(_CHAIN_NAMESPACE, seed))


def derive_signal_id(*, seed: str) -> ArbitrationSignalId:
    if not seed:
        raise ValueError("derive_signal_id requires a non-empty seed")
    return ArbitrationSignalId(uuid.uuid5(_SIGNAL_NAMESPACE, seed))


def derive_conflict_id(*, seed: str) -> ArbitrationConflictId:
    if not seed:
        raise ValueError("derive_conflict_id requires a non-empty seed")
    return ArbitrationConflictId(uuid.uuid5(_CONFLICT_NAMESPACE, seed))


def derive_recommendation_id(
    *, seed: str
) -> ArbitrationRecommendationId:
    if not seed:
        raise ValueError(
            "derive_recommendation_id requires a non-empty seed"
        )
    return ArbitrationRecommendationId(
        uuid.uuid5(_RECOMMENDATION_NAMESPACE, seed)
    )


def derive_finding_id(
    *,
    evaluation_id: uuid.UUID,
    evaluator_name: str,
    code: str,
    ordinal: int,
) -> uuid.UUID:
    """Derive a deterministic per-finding id."""
    seed = f"{evaluation_id}:{evaluator_name}:{code}:{ordinal}"
    return uuid.uuid5(_FINDING_NAMESPACE, seed)


def derive_deadlock_witness_id(
    *, evaluation_id: uuid.UUID, kind: str, ordinal: int
) -> uuid.UUID:
    """Derive a deterministic per-deadlock-witness id."""
    seed = f"{evaluation_id}:{kind}:{ordinal}"
    return uuid.uuid5(_DEADLOCK_NAMESPACE, seed)


# ─── Boundary coercion helpers ───────────────────────────────────────


def as_case_id(value: uuid.UUID | str) -> ArbitrationCaseId:
    return ArbitrationCaseId(
        value if isinstance(value, uuid.UUID) else uuid.UUID(value)
    )


def as_evaluation_id(value: uuid.UUID | str) -> ArbitrationEvaluationId:
    return ArbitrationEvaluationId(
        value if isinstance(value, uuid.UUID) else uuid.UUID(value)
    )


def as_chain_id(value: uuid.UUID | str) -> ArbitrationChainId:
    return ArbitrationChainId(
        value if isinstance(value, uuid.UUID) else uuid.UUID(value)
    )


def as_signal_id(value: uuid.UUID | str) -> ArbitrationSignalId:
    return ArbitrationSignalId(
        value if isinstance(value, uuid.UUID) else uuid.UUID(value)
    )


def as_conflict_id(value: uuid.UUID | str) -> ArbitrationConflictId:
    return ArbitrationConflictId(
        value if isinstance(value, uuid.UUID) else uuid.UUID(value)
    )


def as_recommendation_id(
    value: uuid.UUID | str,
) -> ArbitrationRecommendationId:
    return ArbitrationRecommendationId(
        value if isinstance(value, uuid.UUID) else uuid.UUID(value)
    )


__all__ = [
    "ArbitrationCaseId",
    "ArbitrationEvaluationId",
    "ArbitrationChainId",
    "ArbitrationSignalId",
    "ArbitrationConflictId",
    "ArbitrationRecommendationId",
    "generate_case_id",
    "generate_evaluation_id",
    "generate_signal_id",
    "generate_conflict_id",
    "generate_recommendation_id",
    "derive_case_id",
    "derive_evaluation_id",
    "derive_chain_id",
    "derive_signal_id",
    "derive_conflict_id",
    "derive_recommendation_id",
    "derive_finding_id",
    "derive_deadlock_witness_id",
    "as_case_id",
    "as_evaluation_id",
    "as_chain_id",
    "as_signal_id",
    "as_conflict_id",
    "as_recommendation_id",
]

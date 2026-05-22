"""Deterministic identity helpers.

The supervisor produces several UUID-shaped identifiers
(`finding_id`, `escalation_id`) that downstream consumers correlate
against. For replay-grade determinism we derive these via UUID5 from
stable namespace UUIDs + stable seed strings, so a replay of the same
inputs produces byte-identical identifiers.

`inspection_id` and `decision_id` are *also* derivable but the
runtime defaults to `uuid4()` for them, allowing replay tests to pass
a fixed override while production gets unique-per-call ids by default.
"""

from __future__ import annotations

import uuid

# Namespace UUIDs — stable, hard-coded constants. Changing these is a
# breaking change to every replay-derived identifier in the system.
_FINDING_NAMESPACE = uuid.UUID("a8f4c2d6-1b3e-4f5a-9c7d-1234567890ab")
_ESCALATION_NAMESPACE = uuid.UUID("b2e7d3a8-5c9f-4e6b-8a1d-fedcba987654")
_EVALUATION_NAMESPACE = uuid.UUID("c4d1e8b3-7a2f-4c5e-9b6d-abcdef123456")
_INSPECTION_NAMESPACE = uuid.UUID("d5e2f9c4-8b3a-4d6f-ac7e-bcdef0123456")
_SESSION_INSPECTION_NAMESPACE = uuid.UUID(
    "d5e2f9c4-8b3a-4d6f-ac7e-bcdef0123457"
)
_SESSION_DECISION_NAMESPACE = uuid.UUID(
    "d5e2f9c4-8b3a-4d6f-ac7e-bcdef0123458"
)


def derive_finding_id(
    *, execution_id: uuid.UUID, evaluator_name: str, code: str, ordinal: int
) -> uuid.UUID:
    """Derive a deterministic finding id.

    Two findings produced under the same `(execution_id, evaluator,
    code, ordinal)` always receive the same id. Replays therefore
    produce byte-identical finding identifiers.
    """
    seed = f"{execution_id}:{evaluator_name}:{code}:{ordinal}"
    return uuid.uuid5(_FINDING_NAMESPACE, seed)


def derive_escalation_id(*, decision_id: uuid.UUID, level: str) -> uuid.UUID:
    """Derive a deterministic escalation id from `(decision_id, level)`.

    A single supervisor decision emits at most one escalation per
    level; the namespace+seed combination is therefore unique by
    construction.
    """
    return uuid.uuid5(_ESCALATION_NAMESPACE, f"{decision_id}:{level}")


def derive_evaluation_id(
    *, inspection_id: uuid.UUID, evaluator_name: str
) -> uuid.UUID:
    """Derive a deterministic per-inspection evaluation id.

    Sprint K does not surface evaluation ids on the API but persistence
    backends benefit from a stable primary key per `(inspection,
    evaluator)` row.
    """
    return uuid.uuid5(
        _EVALUATION_NAMESPACE, f"{inspection_id}:{evaluator_name}"
    )


def derive_inspection_id(
    *,
    execution_id: uuid.UUID,
    correlation_id: uuid.UUID | None,
    runtime_instance_id: uuid.UUID,
    nonce: str = "",
) -> uuid.UUID:
    """Derive an inspection id (replay-aid).

    Production callers normally let `SupervisorRuntime` mint a fresh
    `uuid.uuid4()` per inspection; replay tests can override
    `ExecutionInspectionRequest.inspection_id_override` with the value
    returned here so the persisted inspection record uses a stable id.
    """
    seed = f"{execution_id}:{correlation_id}:{runtime_instance_id}:{nonce}"
    return uuid.uuid5(_INSPECTION_NAMESPACE, seed)


def derive_session_inspection_id(
    *,
    session_id: uuid.UUID | str,
    execution_id: uuid.UUID | str,
    tenant_id: str | None,
) -> uuid.UUID:
    """Derive the canonical inspection id for session-based evaluation."""
    seed = f"{session_id}:{execution_id}:{tenant_id}"
    return uuid.uuid5(_SESSION_INSPECTION_NAMESPACE, seed)


def derive_session_decision_id(*, inspection_id: uuid.UUID | str) -> uuid.UUID:
    """Derive the canonical decision id for a session inspection."""
    return uuid.uuid5(_SESSION_DECISION_NAMESPACE, str(inspection_id))


__all__ = [
    "derive_finding_id",
    "derive_escalation_id",
    "derive_evaluation_id",
    "derive_inspection_id",
    "derive_session_decision_id",
    "derive_session_inspection_id",
]

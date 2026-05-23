"""Session identity primitives.

Six typed identifiers, mirroring the discipline of every sibling
substrate:

* `SessionId`            — the canonical id of an operational
                            session. Deterministically derivable
                            from `(scope, tenant, principal,
                            external_handle)`.
* `SessionEventId`       — id of one timeline event.
                            Deterministically derivable from
                            `(session_id, sequence)`.
* `SessionLineageId`     — id of a lineage chain (root session +
                            descendants).
* `SessionCorrelationId` — id of a cross-substrate correlation
                            observation.
* `SessionTraceId`       — id of one runtime call's trace.
* `SessionReconstructionId` — id of one reconstruction call.

Generators / derivers
─────────────────────

* `generate_*` — UUID4 runtime path.
* `derive_*`   — UUID5 over a pinned namespace + seed. Same seed →
                  same UUID bit-for-bit.

The namespaces are PERMANENT constants. Changing one is a
breaking change to every previously derived identifier.
"""

from __future__ import annotations

import uuid
import itertools
from typing import NewType

from app.identity import project_optional_str


# ─── Type aliases ────────────────────────────────────────────────────


SessionId = NewType("SessionId", uuid.UUID)
SessionEventId = NewType("SessionEventId", uuid.UUID)
SessionLineageId = NewType("SessionLineageId", uuid.UUID)
SessionCorrelationId = NewType("SessionCorrelationId", uuid.UUID)
SessionTraceId = NewType("SessionTraceId", uuid.UUID)
SessionReconstructionId = NewType(
    "SessionReconstructionId", uuid.UUID
)


# ─── Permanent namespace constants ───────────────────────────────────


_SESSION_NAMESPACE: uuid.UUID = uuid.UUID(
    "5e551001-0001-4001-8001-000000000001"
)
_EVENT_NAMESPACE: uuid.UUID = uuid.UUID(
    "5e551001-0002-4002-8002-000000000002"
)
_LINEAGE_NAMESPACE: uuid.UUID = uuid.UUID(
    "5e551001-0003-4003-8003-000000000003"
)
_CORRELATION_NAMESPACE: uuid.UUID = uuid.UUID(
    "5e551001-0004-4004-8004-000000000004"
)
_TRACE_NAMESPACE: uuid.UUID = uuid.UUID(
    "5e551001-0005-4005-8005-000000000005"
)
_RECONSTRUCTION_NAMESPACE: uuid.UUID = uuid.UUID(
    "5e551001-0006-4006-8006-000000000006"
)
_RUNTIME_COUNTER = itertools.count()


# ─── Runtime path: fresh UUID4 ───────────────────────────────────────


def generate_session_id() -> SessionId:
    return SessionId(uuid.uuid5(_SESSION_NAMESPACE, _runtime_seed("session")))


def generate_event_id() -> SessionEventId:
    return SessionEventId(uuid.uuid5(_EVENT_NAMESPACE, _runtime_seed("event")))


def generate_lineage_id() -> SessionLineageId:
    return SessionLineageId(uuid.uuid5(_LINEAGE_NAMESPACE, _runtime_seed("lineage")))


def generate_correlation_id() -> SessionCorrelationId:
    return SessionCorrelationId(uuid.uuid5(_CORRELATION_NAMESPACE, _runtime_seed("correlation")))


def generate_trace_id() -> SessionTraceId:
    return SessionTraceId(uuid.uuid5(_TRACE_NAMESPACE, _runtime_seed("trace")))


def generate_reconstruction_id() -> SessionReconstructionId:
    return SessionReconstructionId(uuid.uuid5(_RECONSTRUCTION_NAMESPACE, _runtime_seed("reconstruction")))


def _runtime_seed(label: str) -> str:
    return f"runtime|{label}|{next(_RUNTIME_COUNTER)}"


# ─── Replay-safe deterministic UUID5 ─────────────────────────────────


def derive_session_id(
    *,
    scope: str,
    tenant_id: str | None,
    principal_id: str | None,
    external_handle: str,
) -> SessionId:
    """Derive a deterministic session id.

    Same `(scope, tenant_id, principal_id, external_handle)` →
    byte-identical `SessionId`. Used when a caller needs to
    reconstruct (or de-duplicate) sessions across replays.
    """
    if not scope:
        raise ValueError(
            "derive_session_id requires a non-empty `scope`"
        )
    if not external_handle:
        raise ValueError(
            "derive_session_id requires a non-empty "
            "`external_handle`"
        )
    # ``project_optional_str`` disambiguates ``None`` from ``""`` for
    # BOTH tenant_id and principal_id (Wedge B4 closure of audit
    # CO-2). The same expression carried two collapse defects; both
    # are repaired together for constitutional symmetry — a
    # tenant-less session and an empty-tenant session must derive
    # distinct ``SessionId``s, as must a principal-less session and
    # an empty-principal session.
    seed = (
        f"{scope}|"
        f"{project_optional_str(tenant_id)}|"
        f"{project_optional_str(principal_id)}|"
        f"{external_handle}"
    )
    return SessionId(uuid.uuid5(_SESSION_NAMESPACE, seed))


def derive_event_id(
    *,
    session_id: uuid.UUID,
    sequence: int,
) -> SessionEventId:
    """Derive a deterministic event id from `(session_id, sequence)`.

    Two reconstructions of the same timeline produce byte-identical
    event ids — that's the foundation of replay-equivalent
    timeline rebuilds.
    """
    if sequence < 0:
        raise ValueError(
            "derive_event_id requires a non-negative `sequence`"
        )
    seed = f"{session_id}|{sequence}"
    return SessionEventId(uuid.uuid5(_EVENT_NAMESPACE, seed))


def derive_lineage_id(
    *,
    root_session_id: uuid.UUID,
) -> SessionLineageId:
    """Derive a deterministic lineage id from the root session id."""
    return SessionLineageId(
        uuid.uuid5(_LINEAGE_NAMESPACE, str(root_session_id))
    )


def derive_correlation_id(
    *,
    session_id: uuid.UUID,
    kind: str,
    external_id: str,
) -> SessionCorrelationId:
    """Derive a deterministic cross-substrate correlation id.

    Used by callers that want idempotent recording of the same
    correlation across replays. The substrate uses
    ``(session_id, kind, external_id)`` as the canonical seed.
    """
    if not kind or not external_id:
        raise ValueError(
            "derive_correlation_id requires non-empty `kind` and "
            "`external_id`"
        )
    seed = f"{session_id}|{kind}|{external_id}"
    return SessionCorrelationId(
        uuid.uuid5(_CORRELATION_NAMESPACE, seed)
    )


def derive_trace_id(*, seed: str) -> SessionTraceId:
    if not seed:
        raise ValueError(
            "derive_trace_id requires a non-empty `seed`"
        )
    return SessionTraceId(uuid.uuid5(_TRACE_NAMESPACE, seed))


def derive_reconstruction_id(*, seed: str) -> SessionReconstructionId:
    if not seed:
        raise ValueError(
            "derive_reconstruction_id requires a non-empty `seed`"
        )
    return SessionReconstructionId(
        uuid.uuid5(_RECONSTRUCTION_NAMESPACE, seed)
    )


# ─── Coercion helpers ────────────────────────────────────────────────


def as_session_id(value: uuid.UUID | str) -> SessionId:
    return SessionId(
        value if isinstance(value, uuid.UUID) else uuid.UUID(value)
    )


def as_event_id(value: uuid.UUID | str) -> SessionEventId:
    return SessionEventId(
        value if isinstance(value, uuid.UUID) else uuid.UUID(value)
    )


def as_lineage_id(value: uuid.UUID | str) -> SessionLineageId:
    return SessionLineageId(
        value if isinstance(value, uuid.UUID) else uuid.UUID(value)
    )


def as_correlation_id(
    value: uuid.UUID | str,
) -> SessionCorrelationId:
    return SessionCorrelationId(
        value if isinstance(value, uuid.UUID) else uuid.UUID(value)
    )


__all__ = [
    "SessionCorrelationId",
    "SessionEventId",
    "SessionId",
    "SessionLineageId",
    "SessionReconstructionId",
    "SessionTraceId",
    "as_correlation_id",
    "as_event_id",
    "as_lineage_id",
    "as_session_id",
    "derive_correlation_id",
    "derive_event_id",
    "derive_lineage_id",
    "derive_reconstruction_id",
    "derive_session_id",
    "derive_trace_id",
    "generate_correlation_id",
    "generate_event_id",
    "generate_lineage_id",
    "generate_reconstruction_id",
    "generate_session_id",
    "generate_trace_id",
]

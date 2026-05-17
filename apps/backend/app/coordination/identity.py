"""Coordination identity primitives.

Three typed identifiers underpin the substrate:

* `CoordinationId`         — one per `CoordinationRuntime.dispatch()`
                              call. Identifies the dispatch operation
                              + the persisted envelope.
* `CoordinationMessageId`  — one per logical message. Distinct from
                              `CoordinationId` so a single message
                              CAN appear under multiple dispatches
                              (e.g. a replay reconstruction
                              dispatches the same message
                              identifier under a fresh coordination
                              id).
* `CoordinationCorrelationId`
                           — operational-pipeline grouping. Threads
                              through every dispatch that belongs to
                              one logical operation (multi-agent
                              handoff chain, supervisor inspection
                              chain).

Type discipline: each is a `NewType` over `uuid.UUID`. At runtime
they ARE `uuid.UUID` instances — comparisons, equality, hashability
and `str(...)` all work transparently. The type names exist so
mypy / IDEs and human readers see "is this an ID for the message or
for the dispatch?" at every call site instead of guessing from
context.

Generators / derivers
─────────────────────

Two paths exist for every identifier, mirroring
`app/governance/identity/decision_ids.py`:

* `generate_*`  — UUID4. The runtime path. Unique across live
                   execution; never collides across calls.
* `derive_*`    — UUID5 over a stable namespace + caller-supplied
                   seed. The replay / test path. Same seed → same
                   UUID, bit-for-bit.

The namespaces are pinned constants. Changing one is a breaking
change to every previously-derived identifier in the substrate —
treat them as permanent.
"""

from __future__ import annotations

import uuid
from typing import NewType


# ─── Type aliases (NewType wraps so mypy distinguishes them) ─────────


CoordinationId = NewType("CoordinationId", uuid.UUID)
"""Stable identifier for one `CoordinationRuntime.dispatch()` call."""


CoordinationMessageId = NewType("CoordinationMessageId", uuid.UUID)
"""Stable identifier for one logical coordination message."""


CoordinationCorrelationId = NewType("CoordinationCorrelationId", uuid.UUID)
"""Pipeline-level grouping shared across multiple dispatches."""


# ─── Namespaces — permanent constants ────────────────────────────────


_COORDINATION_NAMESPACE: uuid.UUID = uuid.UUID(
    "6f3a1b1c-2c5e-4f0a-9c2b-1a2b3c4d5e6f"
)
_MESSAGE_NAMESPACE: uuid.UUID = uuid.UUID(
    "7b4e2d2c-3d6f-4a1b-8c3d-2b3c4d5e6f70"
)
_CORRELATION_NAMESPACE: uuid.UUID = uuid.UUID(
    "8c5f3e3d-4e70-4b2c-9d4e-3c4d5e6f7081"
)


# ─── Runtime path: fresh UUID4 per call ──────────────────────────────


def generate_coordination_id() -> CoordinationId:
    """Return a fresh UUID4 wrapped as `CoordinationId`."""
    return CoordinationId(uuid.uuid4())


def generate_message_id() -> CoordinationMessageId:
    """Return a fresh UUID4 wrapped as `CoordinationMessageId`."""
    return CoordinationMessageId(uuid.uuid4())


def generate_correlation_id() -> CoordinationCorrelationId:
    """Return a fresh UUID4 wrapped as `CoordinationCorrelationId`."""
    return CoordinationCorrelationId(uuid.uuid4())


# ─── Replay path: deterministic UUID5 from a stable seed ─────────────


def derive_coordination_id(*, seed: str) -> CoordinationId:
    """Deterministically derive a `CoordinationId` from a stable seed.

    Same seed → same UUID. Used by replay tools and tests that need
    byte-identical envelope identifiers across reconstructions.
    `seed` MUST be non-empty.
    """
    if not seed:
        raise ValueError("derive_coordination_id requires a non-empty seed")
    return CoordinationId(uuid.uuid5(_COORDINATION_NAMESPACE, seed))


def derive_message_id(*, seed: str) -> CoordinationMessageId:
    """Deterministically derive a `CoordinationMessageId` from a seed."""
    if not seed:
        raise ValueError("derive_message_id requires a non-empty seed")
    return CoordinationMessageId(uuid.uuid5(_MESSAGE_NAMESPACE, seed))


def derive_correlation_id(*, seed: str) -> CoordinationCorrelationId:
    """Deterministically derive a `CoordinationCorrelationId` from a seed."""
    if not seed:
        raise ValueError("derive_correlation_id requires a non-empty seed")
    return CoordinationCorrelationId(uuid.uuid5(_CORRELATION_NAMESPACE, seed))


# ─── Boundary coercion helpers ───────────────────────────────────────


def as_coordination_id(value: uuid.UUID | str) -> CoordinationId:
    """Coerce a raw UUID / string into the typed identifier.

    Used at persistence boundaries — records carry stringified UUIDs;
    runtime types carry the typed `NewType`. Always validates that
    the input is UUID-shaped.
    """
    return CoordinationId(value if isinstance(value, uuid.UUID) else uuid.UUID(value))


def as_message_id(value: uuid.UUID | str) -> CoordinationMessageId:
    return CoordinationMessageId(
        value if isinstance(value, uuid.UUID) else uuid.UUID(value)
    )


def as_correlation_id(value: uuid.UUID | str) -> CoordinationCorrelationId:
    return CoordinationCorrelationId(
        value if isinstance(value, uuid.UUID) else uuid.UUID(value)
    )


__all__ = [
    "CoordinationId",
    "CoordinationMessageId",
    "CoordinationCorrelationId",
    "generate_coordination_id",
    "generate_message_id",
    "generate_correlation_id",
    "derive_coordination_id",
    "derive_message_id",
    "derive_correlation_id",
    "as_coordination_id",
    "as_message_id",
    "as_correlation_id",
]

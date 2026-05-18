"""Event identifier + deterministic derivation (P2-D).

:class:`EventId` is a ``NewType`` over ``str`` (UUIDv5 string). The
type marker keeps event ids structurally distinct from other ids
without paying runtime cost.

:func:`derive_event_id` is the replay-safe identifier derivation. It
mirrors the canonicalization discipline established by Wedge B4
(NUL-bounded ``None`` projection via
:func:`app.identity.project_optional_str`) so that
``parent_event_id=None`` and ``parent_event_id=""`` never collapse
onto the same id.
"""

from __future__ import annotations

import uuid
from typing import NewType

from app.identity import project_optional_str


EventId = NewType("EventId", str)


# Deterministic namespace for OperationalEvent identifiers.
# Generated once via ``uuid.uuid4()`` and pinned here; the value is
# stable across releases. Changing it would break every existing
# replay anchor.
_EVENT_NAMESPACE = uuid.UUID("3f8b6c4e-5b27-4a92-9c1a-1c8b1f0c7c2d")


def derive_event_id(
    *,
    operational_act: str,
    substrate: str,
    runtime_instance_id: uuid.UUID,
    sequence: int,
    tenant_id: str | None,
    parent_event_id: str | None,
) -> EventId:
    """Deterministic UUIDv5 event identifier.

    The seed is a pipe-joined concatenation of every input axis;
    ``None`` is projected to a NUL-bounded sentinel to preserve the
    constitutional distinction between "unset" and "empty string".
    """
    seed = "|".join(
        [
            operational_act,
            substrate,
            str(runtime_instance_id),
            str(sequence),
            project_optional_str(tenant_id),
            project_optional_str(parent_event_id),
        ]
    )
    return EventId(str(uuid.uuid5(_EVENT_NAMESPACE, seed)))


__all__ = ["EventId", "derive_event_id"]

"""Pure lineage construction helpers.

Two construction modes:

* `build_lineage_for_root(session_id)` — open a new lineage chain
                        with `session_id` as both root and self.
* `build_lineage_for_child(session_id, parent_lineage)` — extend
                        an existing lineage by one generation.

The helpers assert no cycles and preserve the invariant that
``lineage_id == derive_lineage_id(root_session_id)`` for every
session in the chain.
"""

from __future__ import annotations

from app.session.exceptions import SessionLineageError
from app.session.identity import (
    SessionId,
    derive_lineage_id,
)
from app.session.models.lineage import SessionLineage


def build_lineage_for_root(
    *,
    session_id: SessionId,
) -> SessionLineage:
    """Build the lineage record for a fresh root session."""
    return SessionLineage(
        lineage_id=derive_lineage_id(
            root_session_id=session_id
        ),
        session_id=session_id,
        root_session_id=session_id,
        parent_session_id=None,
        ancestor_session_ids=(),
        depth=0,
    )


def build_lineage_for_child(
    *,
    session_id: SessionId,
    parent_lineage: SessionLineage,
) -> SessionLineage:
    """Build the lineage record for a child session.

    Raises:
        SessionLineageError: if the proposed child id appears
            anywhere in the parent's ancestry chain (cycle).
    """
    if session_id in parent_lineage.ancestor_session_ids:
        raise SessionLineageError(
            "cycle detected: proposed session id is already an "
            "ancestor"
        )
    if session_id == parent_lineage.session_id:
        raise SessionLineageError(
            "cycle detected: proposed session id equals parent "
            "session id"
        )
    ancestors = (
        parent_lineage.ancestor_session_ids
        + (parent_lineage.session_id,)
    )
    return SessionLineage(
        lineage_id=parent_lineage.lineage_id,
        session_id=session_id,
        root_session_id=parent_lineage.root_session_id,
        parent_session_id=parent_lineage.session_id,
        ancestor_session_ids=ancestors,
        depth=parent_lineage.depth + 1,
    )


def extend_lineage(
    *,
    parent_lineage: SessionLineage,
    new_descendant_id: SessionId,
) -> SessionLineage:
    """Convenience wrapper around `build_lineage_for_child`."""
    return build_lineage_for_child(
        session_id=new_descendant_id,
        parent_lineage=parent_lineage,
    )


__all__ = [
    "build_lineage_for_child",
    "build_lineage_for_root",
    "extend_lineage",
]

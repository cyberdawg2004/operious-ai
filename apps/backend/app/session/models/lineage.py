"""`SessionLineage` — immutable ancestry record.

Lineage describes WHICH SESSIONS PRECEDED THIS ONE. It NEVER
implies execution flow — a parent session is not a "previous
step"; it's a continuity ancestor. The substrate forbids cycles
explicitly (a session cannot be its own ancestor).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.session.identity import SessionId, SessionLineageId


@dataclass(frozen=True, slots=True)
class SessionLineage:
    """Immutable lineage record for a session.

    Attributes:
        lineage_id:           Stable identifier for the lineage
                               chain (deterministically derived
                               from `root_session_id`).
        session_id:           Session this lineage record anchors.
        root_session_id:      Topmost ancestor in the chain.
        parent_session_id:    Immediate predecessor.
                               ``None`` when the session itself
                               IS the root.
        ancestor_session_ids: Full ordered ancestry chain
                               (root-first → parent-last).
                               Excludes `session_id` itself.
        depth:                Length of the ancestry chain.
                               ``0`` for the root session.
    """

    lineage_id: SessionLineageId
    session_id: SessionId
    root_session_id: SessionId
    parent_session_id: SessionId | None
    ancestor_session_ids: tuple[SessionId, ...]
    depth: int

    def __post_init__(self) -> None:
        if self.session_id in self.ancestor_session_ids:
            raise ValueError(
                "SessionLineage cycle detected: session cannot be "
                "its own ancestor"
            )
        if self.depth != len(self.ancestor_session_ids):
            raise ValueError(
                "SessionLineage.depth must equal "
                "len(ancestor_session_ids)"
            )
        if (
            self.parent_session_id is not None
            and (
                not self.ancestor_session_ids
                or self.ancestor_session_ids[-1]
                != self.parent_session_id
            )
        ):
            raise ValueError(
                "SessionLineage.parent_session_id must be the last "
                "entry in ancestor_session_ids"
            )
        if (
            self.parent_session_id is None
            and self.session_id != self.root_session_id
        ):
            raise ValueError(
                "SessionLineage with no parent must be its own root"
            )

    @property
    def is_root(self) -> bool:
        return self.parent_session_id is None


__all__ = ["SessionLineage"]

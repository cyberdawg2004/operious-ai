"""`CoordinationRegistry` — name-keyed, sorted-id iteration.

Same discipline as `EvaluatorRegistry` (supervisor), `PolicyRegistry`
(governance), `AgentRegistry` (agents), `ToolRegistry` (tools):

* explicit registration at composition time,
* duplicate registration is a configuration error,
* `__iter__` yields participants in **sorted-id order** so
  introspection / replay output is deterministic,
* `names()` returns the sorted id tuple — the canonical
  "what's registered" handle.

The registry is the only authority on whether a sender / recipient
identity is recognised; `CoordinationRuntime` consults it during
the validate phase of `dispatch()`.
"""

from __future__ import annotations

from typing import Iterator

from app.coordination.exceptions import CoordinationValidationError
from app.coordination.models.participants import CoordinationParticipant


class CoordinationRegistry:
    """Participant-id → participant lookup with deterministic iteration."""

    def __init__(self) -> None:
        self._participants: dict[str, CoordinationParticipant] = {}

    # ─── Mutation (composition time) ─────────────────────────────────

    def register(self, participant: CoordinationParticipant) -> None:
        """Register `participant`. Duplicate ids raise."""
        if not participant.participant_id:
            raise CoordinationValidationError(
                "participant must declare a non-empty participant_id"
            )
        if participant.participant_id in self._participants:
            raise CoordinationValidationError(
                f"participant already registered: "
                f"{participant.participant_id!r}"
            )
        self._participants[participant.participant_id] = participant

    # ─── Reads ───────────────────────────────────────────────────────

    def get(self, participant_id: str) -> CoordinationParticipant:
        """Return the registered participant. Raises on unknown id."""
        if participant_id not in self._participants:
            raise CoordinationValidationError(
                f"unknown coordination participant: {participant_id!r}"
            )
        return self._participants[participant_id]

    def has(self, participant_id: str) -> bool:
        """Return True iff `participant_id` is registered."""
        return participant_id in self._participants

    def names(self) -> tuple[str, ...]:
        """Every registered participant id in sorted order."""
        return tuple(sorted(self._participants.keys()))

    # ─── Iteration ───────────────────────────────────────────────────

    def __iter__(self) -> Iterator[CoordinationParticipant]:
        """Yield participants in deterministic sorted-id order."""
        for participant_id in sorted(self._participants.keys()):
            yield self._participants[participant_id]

    def __len__(self) -> int:
        return len(self._participants)

    def __contains__(self, participant_id: object) -> bool:
        return isinstance(participant_id, str) and participant_id in self._participants


__all__ = ["CoordinationRegistry"]

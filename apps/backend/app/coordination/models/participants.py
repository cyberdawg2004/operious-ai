"""`CoordinationParticipant` — registered participant identity.

A participant is any named entity the substrate accepts as a sender
or recipient of coordination messages. Registration is explicit:
the `CoordinationRegistry` is populated at composition time and
the runtime validates that both `sender_id` and recipient identity
appear in the registry (Rule 1 — coordination is mediated, not
ambient).

Participants are deliberately thin — the registry is an identity
boundary, not an addressing/transport layer. Concrete agent
implementations live in `app/agents/`; the coordination substrate
only needs the identity + kind to authorise the dispatch and
record the lineage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class CoordinationParticipant:
    """Registered participant identity (sender or recipient).

    Attributes:
        participant_id: Stable identifier. The registry keys on this.
                        Conventionally namespaced (``"agent:retriever"``,
                        ``"supervisor:default"``, ``"runtime:rag"``)
                        so audit dashboards can group by prefix.
        kind:           Free-form classification (mirrors
                        `CoordinationRecipient.kind`).
        tenant_id:      Optional tenant scope.
        metadata:       Free-form, propagated through audit / replay.
    """

    participant_id: str
    kind: str = "agent"
    tenant_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])

    def to_dict(self) -> dict[str, Any]:
        return {
            "participant_id": self.participant_id,
            "kind": self.kind,
            "tenant_id": self.tenant_id,
            "metadata": dict(self.metadata),
        }


__all__ = ["CoordinationParticipant"]

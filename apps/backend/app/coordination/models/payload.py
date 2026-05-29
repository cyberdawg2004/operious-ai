"""`CoordinationPayload` — typed, immutable, replay-safe message body.

The payload is the **only** place coordination messages carry
caller-supplied content. Everything else on a `CoordinationMessage`
is substrate-controlled (sender, recipient, type, priority,
identifiers, timestamps). Keeping content quarantined to one slot
makes governance inspection, redaction, and audit reads
unambiguous.

Replay-safety contract:

* `body` is a plain `Mapping[str, Any]` — callers MUST only pass
  JSON-coercible values (str / int / float / bool / None / list / dict).
  Persistence layers refuse other types; replay reconstructions
  compare on the serialised form.
* `content_type` is a stable identifier (e.g. ``"application/json"``,
  ``"operious/agent-handoff"``). Recipients dispatch on it.
* `schema_version` is a free-form version string — callers MUST bump
  it when the body shape changes so replay tooling can branch.

`to_dict()` / `from_dict()` provide the canonical serialisation;
they preserve insertion ordering of `body` (Python ≥ 3.7 dicts) so
JSON serialisations are byte-stable for fixed inputs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class CoordinationPayload:
    """Immutable typed payload for one coordination message.

    Attributes:
        content_type:   Stable identifier the recipient dispatches on.
                        Examples: ``"application/json"``,
                        ``"operious/agent-handoff"``,
                        ``"operious/supervisor-finding"``.
        body:           JSON-coercible payload data. The substrate
                        never inspects body contents; governance
                        policies that need to may do so via their own
                        subject shape.
        schema_version: Caller-controlled version tag (default ``"1"``).
                        Bump when the body shape changes.
        metadata:       Free-form, propagated through persistence.
    """

    content_type: str
    body: dict[str, Any] = field(default_factory=dict[str, Any])
    schema_version: str = "1"
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])

    def to_dict(self) -> dict[str, Any]:
        return {
            "content_type": self.content_type,
            "schema_version": self.schema_version,
            "body": dict(self.body),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CoordinationPayload":
        return cls(
            content_type=str(data["content_type"]),
            schema_version=str(data.get("schema_version", "1")),
            body=dict(data.get("body") or {}),
            metadata=dict(data.get("metadata") or {}),
        )


__all__ = ["CoordinationPayload"]

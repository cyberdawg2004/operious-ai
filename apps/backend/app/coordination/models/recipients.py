"""`CoordinationRecipient` — typed, explicit recipient identity.

Every coordination dispatch carries exactly one recipient value
object. The recipient is the substrate's notion of "who receives
the message" — agent, supervisor, runtime, or broadcast scope. The
runtime uses the recipient identity to:

* validate the recipient is known (against `CoordinationRegistry`),
* compose the `GovernanceContext.resource` for the governance
  evaluation,
* persist a queryable identity on the envelope.

Recipients are **identity references**, NOT live handles. The
substrate never invokes the recipient; it merely records the
identity. Subsequent invocation is the orchestration layer's
responsibility (Rule 5 — `CoordinationRuntime` does not execute
agents).

The `kind` field is a free-form string the surrounding deployment
defines — typical values include ``"agent"``, ``"supervisor"``,
``"runtime"``, ``"external"``, ``"broadcast"``. Kept untyped so new
participant kinds don't require a substrate enum change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class CoordinationRecipient:
    """Typed recipient identity for one coordination dispatch.

    Attributes:
        recipient_id:    Stable identifier of the receiver (e.g.
                         ``"agent:retriever"``, ``"supervisor:default"``,
                         ``"broadcast:tenant:acme"``).
        kind:            Free-form classification (``"agent"`` /
                         ``"supervisor"`` / ``"runtime"`` /
                         ``"external"`` / ``"broadcast"``). Recorded
                         verbatim onto the envelope.
        tenant_id:       Optional tenant scope; surfaces on the
                         envelope and the governance context.
        metadata:        Free-form, propagated through persistence.
    """

    recipient_id: str
    kind: str = "agent"
    tenant_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "recipient_id": self.recipient_id,
            "kind": self.kind,
            "tenant_id": self.tenant_id,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CoordinationRecipient":
        return cls(
            recipient_id=str(data["recipient_id"]),
            kind=str(data.get("kind", "agent")),
            tenant_id=(
                str(data["tenant_id"])
                if data.get("tenant_id") is not None
                else None
            ),
            metadata=dict(data.get("metadata") or {}),
        )


__all__ = ["CoordinationRecipient"]

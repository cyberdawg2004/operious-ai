"""Communication governance subject — future-proofing for comms runtime.

Same design discipline as `agent_actions`: stubbed in place. The
contract exists so the future communication runtime integrates as
addition, not migration.

Use cases the shape anticipates:

* outbound notifications / messages (channel, recipient_scope),
* content-safety policies (content_summary, attachment_metadata),
* escalation flags (out-of-band notification of operators when
  policies decide a communication requires human review).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from app.governance.subjects.base import BaseGovernanceSubject, SubjectKind
from app.types.json import JsonObject


def _empty_json_object() -> JsonObject:
    return {}


@dataclass(frozen=True, slots=True)
class AttachmentSummary:
    """Compact summary of one communication attachment for governance.

    Carries metadata only — the actual content is referenced by id /
    URL. Governance policies that need content inspection summarise
    further upstream (e.g. content-scan service produces a digest +
    classification, which lands here).
    """

    attachment_id: str
    mime_type: str
    size_bytes: int
    classification: str | None = None
    digest: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "attachment_id": self.attachment_id,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "classification": self.classification,
            "digest": self.digest,
        }


@dataclass(frozen=True, slots=True)
class CommunicationGovernanceSubject(BaseGovernanceSubject):
    """Governance subject for a communication being prepared / dispatched.

    Attributes:
        channel:             Stable channel identifier (e.g. "email",
                             "slack", "webhook:tenant:acme:outbox").
        recipient_scope:     Whom the communication targets ("internal",
                             "tenant:acme", "external:vendor:foo").
                             Free-form structured string; comms runtime
                             defines the vocabulary.
        content_summary:     Compact summary of what's being sent
                             (subject, classification, etc.) — NOT the
                             full body. Body inspection happens before
                             governance; governance reads the summary.
        attachment_metadata: Per-attachment summaries.
        escalation_flags:    Stable flags requesting out-of-band
                             handling (e.g. "requires_legal_review",
                             "requires_human_approval").
        request_id:          Platform-wide request lineage id.
        tenant_id:           Tenant scope.
        metadata:            Free-form structured payload.
    """

    channel: str = ""
    recipient_scope: str = ""
    content_summary: str = ""
    attachment_metadata: tuple[AttachmentSummary, ...] = ()
    escalation_flags: tuple[str, ...] = ()
    request_id: str | None = None
    tenant_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=_empty_json_object)
    kind: SubjectKind = SubjectKind.COMMUNICATION

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "channel": self.channel,
            "recipient_scope": self.recipient_scope,
            "content_summary": self.content_summary,
            "attachment_metadata": [a.to_dict() for a in self.attachment_metadata],
            "escalation_flags": list(self.escalation_flags),
            "request_id": self.request_id,
            "tenant_id": self.tenant_id,
            "metadata": dict(self.metadata),
        }


__all__ = ["CommunicationGovernanceSubject", "AttachmentSummary"]

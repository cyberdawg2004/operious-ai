"""Governed auto-send intent creation for ready resolution drafts."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, cast

from app.boundary.outbound.send_outbox import (
    OutboundSendOutboxPersistenceProtocol,
    OutboundSendOutboxRecord,
    make_outbound_send_outbox_record,
)
from app.governance.enums import Decision
from app.governance.persistence import (
    BaseGovernanceRepository,
    GovernanceDecisionRecord,
)
from app.resolution.enums import (
    ResolutionOutboundDraftStatus,
    ResolutionProposalStatus,
)
from app.resolution.identity import derive_resolution_outbound_draft_id
from app.resolution.persistence import (
    ResolutionOutboundDraftRecord,
    ResolutionProposalRecord,
)

CUSTOMER_REPLY_SEND_ACTION = "customer_reply.send"
SUPPORTED_AUTO_SEND_CHANNELS = frozenset(("email", "whatsapp"))
_COMMUNICATION_SUBJECT_KIND = "communication"
_SECRET_KEY_FRAGMENTS = (
    "authorization",
    "credential",
    "key",
    "password",
    "secret",
    "token",
)


def _empty_metadata() -> dict[str, Any]:
    return {}


@dataclass(frozen=True, slots=True)
class OutboundSendTarget:
    """Concrete tenant boundary target for a governed customer reply."""

    channel: str
    recipient: str
    source: str | None = None
    subject: str | None = None
    thread_context: str | None = None
    in_reply_to_message_id: str | None = None
    references_header: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=_empty_metadata)


@dataclass(frozen=True, slots=True)
class OutboundAutoSendRefusalReason:
    """Terminal reason for refusing a governed auto-send attempt."""

    code: str
    message: str


@dataclass(frozen=True, slots=True)
class OutboundAutoSendRequestResult:
    """Outcome of a governed auto-send request attempt."""

    outbox: OutboundSendOutboxRecord | None
    reason: OutboundAutoSendRefusalReason | None = None


class OutboundAutoSendService:
    """Create retryable send intents only for exact persisted ALLOW decisions."""

    def __init__(
        self,
        *,
        governance_repository: BaseGovernanceRepository,
        outbox_persistence: OutboundSendOutboxPersistenceProtocol,
    ) -> None:
        self._governance_repository = governance_repository
        self._outbox_persistence = outbox_persistence

    async def request_auto_send(
        self,
        *,
        draft: ResolutionOutboundDraftRecord,
        proposal: ResolutionProposalRecord,
        target: OutboundSendTarget,
        expected_tenant_id: str,
        created_at: datetime | None = None,
    ) -> OutboundAutoSendRequestResult:
        """Create one durable send intent, or return a typed terminal refusal."""

        tenant_id = expected_tenant_id.strip()
        if not tenant_id:
            raise ValueError("expected_tenant_id must be non-empty")
        channel = _normalized_channel(target.channel)
        recipient = _optional_text(target.recipient)
        thread_context = _optional_text(target.thread_context)
        if (
            channel not in SUPPORTED_AUTO_SEND_CHANNELS
            or recipient is None
            or thread_context is None
        ):
            return OutboundAutoSendRequestResult(
                outbox=None,
                reason=OutboundAutoSendRefusalReason(
                    code="unsupported_target",
                    message="governed auto-send target is unsupported",
                ),
            )
        # Surface the upstream governance denial reason before the generic
        # lineage check so operators see "severe_resolution_risk" (or similar)
        # rather than the opaque "missed exact proposal/draft lineage" message.
        if (
            proposal.status is ResolutionProposalStatus.DENIED
            and draft.status is ResolutionOutboundDraftStatus.DENIED
        ):
            return OutboundAutoSendRequestResult(
                outbox=None,
                reason=await _governance_denied_reason(
                    governance_repository=self._governance_repository,
                    draft=draft,
                    tenant_id=tenant_id,
                ),
            )
        if not _draft_and_proposal_are_exact(
            draft=draft,
            proposal=proposal,
            expected_tenant_id=tenant_id,
        ):
            return OutboundAutoSendRequestResult(
                outbox=None,
                reason=OutboundAutoSendRefusalReason(
                    code="governance_miss",
                    message="governed auto-send missed exact proposal/draft lineage",
                ),
            )
        governance_decision_id = draft.governance_decision_id
        if governance_decision_id is None:
            return OutboundAutoSendRequestResult(
                outbox=None,
                reason=OutboundAutoSendRefusalReason(
                    code="governance_miss",
                    message="governed auto-send missed governance decision linkage",
                ),
            )
        decision = await self._governance_repository.get_decision(
            str(governance_decision_id),
            expected_tenant_id=tenant_id,
        )
        if decision is None:
            return OutboundAutoSendRequestResult(
                outbox=None,
                reason=OutboundAutoSendRefusalReason(
                    code="governance_miss",
                    message="governed auto-send decision was not found",
                ),
            )
        canonical_reply = _canonical_reply_for_governance(draft)
        if not _decision_is_exact_send_allow(
            decision=decision,
            tenant_id=tenant_id,
            proposal=proposal,
            draft=draft,
            channel=channel,
            recipient=recipient,
            thread_context=thread_context,
            canonical_reply=canonical_reply,
        ):
            return OutboundAutoSendRequestResult(
                outbox=None,
                reason=OutboundAutoSendRefusalReason(
                    code="governance_miss",
                    message="governed auto-send decision was not an exact allow",
                ),
            )
        record = make_outbound_send_outbox_record(
            tenant_id=tenant_id,
            channel=channel,
            action=CUSTOMER_REPLY_SEND_ACTION,
            draft_id=draft.draft_id,
            proposal_id=proposal.proposal_id,
            session_id=_required_lineage_text(draft.session_id),
            dispatch_id=_required_lineage_text(draft.dispatch_id),
            governance_decision_id=governance_decision_id,
            recipient=recipient,
            draft_body_sha256=draft.draft_body_sha256,
            created_at=created_at or datetime.now(tz=timezone.utc),
            metadata=_safe_outbox_metadata(
                target=target,
                proposal=proposal,
                draft=draft,
                channel=channel,
            ),
        )
        outbox = await self._outbox_persistence.create_outbound_send_outbox(record)
        return OutboundAutoSendRequestResult(outbox=outbox)


async def _governance_denied_reason(
    *,
    governance_repository: BaseGovernanceRepository,
    draft: ResolutionOutboundDraftRecord,
    tenant_id: str,
) -> OutboundAutoSendRefusalReason:
    """Return a clearer refusal reason when the proposal was governance-DENIED.

    Looks up the stored governance decision to surface the specific violation
    rule (e.g. severe_resolution_risk) instead of the generic lineage-miss.
    """
    rule_ids: tuple[str, ...] = ()
    if draft.governance_decision_id is not None:
        decision = await governance_repository.get_decision(
            str(draft.governance_decision_id),
            expected_tenant_id=tenant_id,
        )
        if decision is not None:
            rule_ids = tuple(
                v.rule_id
                for v in decision.violations
                if v.decision == Decision.DENY.value
            )
    detail = ", ".join(rule_ids) if rule_ids else "governance denied"
    return OutboundAutoSendRefusalReason(
        code="proposal_governance_denied",
        message=f"auto-send held for review: {detail}",
    )


def _draft_and_proposal_are_exact(
    *,
    draft: ResolutionOutboundDraftRecord,
    proposal: ResolutionProposalRecord,
    expected_tenant_id: str,
) -> bool:
    return (
        draft.tenant_id == expected_tenant_id
        and proposal.tenant_id == expected_tenant_id
        and draft.proposal_id == proposal.proposal_id
        and draft.session_id == proposal.session_id
        and draft.execution_id == proposal.execution_id
        and draft.dispatch_id == proposal.dispatch_id
        and draft.governance_decision_id is not None
        and draft.governance_decision_id == proposal.governance_decision_id
        and draft.status is ResolutionOutboundDraftStatus.READY
        and proposal.status is ResolutionProposalStatus.SEND_ELIGIBLE
        and draft.draft_body_sha256 == _sha256_text(draft.draft_body)
        and draft.draft_id
        == derive_resolution_outbound_draft_id(
            tenant_id=expected_tenant_id,
            proposal_id=proposal.proposal_id,
        )
    )


def _decision_is_exact_send_allow(
    *,
    decision: GovernanceDecisionRecord,
    tenant_id: str,
    proposal: ResolutionProposalRecord,
    draft: ResolutionOutboundDraftRecord,
    channel: str,
    recipient: str,
    thread_context: str,
    canonical_reply: str,
) -> bool:
    metadata = decision.metadata
    return (
        decision.tenant_id == tenant_id
        and decision.decision == Decision.ALLOW.value
        and decision.subject_kind == _COMMUNICATION_SUBJECT_KIND
        and _metadata_text(metadata, "proposal_id") == str(proposal.proposal_id)
        and _metadata_text(metadata, "session_id") == _required_lineage_text(
            draft.session_id
        )
        and _metadata_text(metadata, "execution_id") == _required_lineage_text(
            draft.execution_id
        )
        and _metadata_text(metadata, "dispatch_id") == _required_lineage_text(
            draft.dispatch_id
        )
        and _metadata_text(metadata, "draft_id") == str(draft.draft_id)
        and _metadata_text(metadata, "governed_action")
        == CUSTOMER_REPLY_SEND_ACTION
        and _metadata_text(metadata, "source_channel") == channel
        and _metadata_text(metadata, "reply_recipient") == recipient
        and _metadata_text(metadata, "reply_thread_context") == thread_context
        and _metadata_text(metadata, "proposed_reply_sha256")
        == _sha256_text(canonical_reply)
    )


def _safe_outbox_metadata(
    *,
    target: OutboundSendTarget,
    proposal: ResolutionProposalRecord,
    draft: ResolutionOutboundDraftRecord,
    channel: str,
) -> dict[str, Any]:
    metadata = {
        "source": _optional_text(target.source),
        "subject": _optional_text(target.subject),
        "reply_recipient": _optional_text(target.recipient),
        "reply_thread_context": _optional_text(target.thread_context),
        "in_reply_to_message_id": _optional_text(target.in_reply_to_message_id),
        "references_header": _optional_text(target.references_header),
        "source_channel": channel,
        "proposal_id": str(proposal.proposal_id),
        "session_id": draft.session_id,
        "execution_id": draft.execution_id,
        "dispatch_id": draft.dispatch_id,
    }
    for key, value in target.metadata.items():
        text_key = str(key)
        if _is_sensitive_metadata_key(text_key):
            continue
        metadata[text_key] = _sanitize_metadata_value(value)
    return {
        key: value
        for key, value in metadata.items()
        if value is not None
    }


def _canonical_reply_for_governance(draft: ResolutionOutboundDraftRecord) -> str:
    value = draft.metadata.get("canonical_reply")
    if isinstance(value, str) and value.strip():
        return value
    return draft.draft_body


def _metadata_text(metadata: Mapping[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalized_channel(value: str) -> str:
    return value.strip().lower()


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def _required_lineage_text(value: str | None) -> str:
    return value.strip() if value is not None else ""


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _is_sensitive_metadata_key(key: str) -> bool:
    normalized = key.lower()
    return any(fragment in normalized for fragment in _SECRET_KEY_FRAGMENTS)


def _sanitize_metadata_value(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for key, inner_value in cast(Mapping[object, object], value).items():
            text_key = str(key)
            if _is_sensitive_metadata_key(text_key):
                continue
            sanitized_value = _sanitize_metadata_value(inner_value)
            if sanitized_value is not None:
                sanitized[text_key] = sanitized_value
        return sanitized
    if isinstance(value, list | tuple):
        return [
            sanitized_item
            for item in cast(Iterable[object], value)
            if (sanitized_item := _sanitize_metadata_value(item)) is not None
        ]
    return None


__all__ = [
    "CUSTOMER_REPLY_SEND_ACTION",
    "OutboundAutoSendRefusalReason",
    "OutboundAutoSendRequestResult",
    "OutboundAutoSendService",
    "OutboundSendTarget",
    "SUPPORTED_AUTO_SEND_CHANNELS",
]

"""Conversation Inbox transport schemas — wire shapes for /inbox endpoints.

All projections go from InboxService domain records to frozen Pydantic schemas.
No substrate imports here — uses only service layer records.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.services.inbox_service import (
    InboxConversationSummaryPage,
    InboxConversationSummaryRecord,
    InboxGovernanceContext as _SvcGovernanceContext,
    InboxMessage,
    InboxThreadRecord,
)


class InboxGovernanceContextResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    proposal_id: str
    governance_verdict: str
    autonomy_decision: str
    supervisor_verdict: str
    status: str
    resolution_category: str
    confidence: float
    governance_decision_id: str | None = None

    @classmethod
    def from_domain(cls, ctx: _SvcGovernanceContext) -> "InboxGovernanceContextResponse":
        return cls(
            proposal_id=ctx.proposal_id,
            governance_verdict=ctx.governance_verdict,
            autonomy_decision=ctx.autonomy_decision,
            supervisor_verdict=ctx.supervisor_verdict,
            status=ctx.status,
            resolution_category=ctx.resolution_category,
            confidence=ctx.confidence,
            governance_decision_id=ctx.governance_decision_id,
        )


class InboxThreadMessageResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str
    sequence: int
    role: str
    content: str
    occurred_at: str
    governance: InboxGovernanceContextResponse | None = None
    governance_decision_id: str | None = None

    @classmethod
    def from_domain(cls, msg: InboxMessage) -> "InboxThreadMessageResponse":
        return cls(
            event_id=msg.event_id,
            sequence=msg.sequence,
            role=msg.role,
            content=msg.content,
            occurred_at=msg.occurred_at.isoformat(),
            governance=(
                InboxGovernanceContextResponse.from_domain(msg.governance)
                if msg.governance is not None
                else None
            ),
            governance_decision_id=msg.governance_decision_id,
        )


class InboxThreadResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str
    external_handle: str
    channel: str
    lifecycle_phase: str
    opened_at: str
    customer_identity_id: str | None = None
    messages: list[InboxThreadMessageResponse] = Field(default_factory=list)
    total: int

    @classmethod
    def from_domain(cls, record: InboxThreadRecord) -> "InboxThreadResponse":
        messages = [InboxThreadMessageResponse.from_domain(m) for m in record.messages]
        return cls(
            session_id=record.session_id,
            external_handle=record.external_handle,
            channel=record.channel,
            lifecycle_phase=record.lifecycle_phase,
            opened_at=record.opened_at.isoformat(),
            customer_identity_id=record.customer_identity_id,
            messages=messages,
            total=len(messages),
        )


class InboxConversationSummaryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str
    external_handle: str
    channel: str
    lifecycle_phase: str
    opened_at: str
    last_message_at: str | None = None
    message_count: int
    customer_identity_id: str | None = None
    has_governance_context: bool

    @classmethod
    def from_domain(
        cls, record: InboxConversationSummaryRecord
    ) -> "InboxConversationSummaryResponse":
        return cls(
            session_id=record.session_id,
            external_handle=record.external_handle,
            channel=record.channel,
            lifecycle_phase=record.lifecycle_phase,
            opened_at=record.opened_at.isoformat(),
            last_message_at=(
                record.last_message_at.isoformat()
                if record.last_message_at is not None
                else None
            ),
            message_count=record.message_count,
            customer_identity_id=record.customer_identity_id,
            has_governance_context=record.has_governance_context,
        )


class InboxConversationsPageResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[InboxConversationSummaryResponse] = Field(default_factory=list)
    total: int
    limit: int
    offset: int

    @classmethod
    def from_domain(cls, page: InboxConversationSummaryPage) -> "InboxConversationsPageResponse":
        return cls(
            items=[InboxConversationSummaryResponse.from_domain(r) for r in page.items],
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )


__all__ = [
    "InboxConversationSummaryResponse",
    "InboxConversationsPageResponse",
    "InboxGovernanceContextResponse",
    "InboxThreadMessageResponse",
    "InboxThreadResponse",
]

"""Service layer for the Conversation Inbox (manager-facing read-only view).

Combines session_events (inbound/outbound message bodies) with resolution
proposals (governance verdicts) into a unified thread view per session.

The router inbox.py uses ONLY this service through Depends(get_inbox_service);
it never touches substrate repositories directly — satisfying the router
constitutional invariants.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.resolution.persistence.models import ResolutionProposalQuery
from app.resolution.persistence.postgres import PostgresResolutionProposalPersistence
from app.session.enums import SessionEventKind, SessionLifecyclePhase
from app.session.identity import SessionId
from app.session.persistence import (
    SessionEventQuery,
    SessionPersistenceProtocol,
    SessionQuery,
)
from app.session.persistence.records import SessionRecord

_CONVERSATION_KINDS = frozenset(
    [SessionEventKind.CUSTOMER_MESSAGE, SessionEventKind.ASSISTANT_RESPONSE]
)


# ── Data contracts ────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class InboxGovernanceContext:
    proposal_id: str
    governance_verdict: str
    autonomy_decision: str
    supervisor_verdict: str
    status: str
    resolution_category: str
    confidence: float
    governance_decision_id: str | None


@dataclass(frozen=True, slots=True)
class InboxMessage:
    event_id: str
    sequence: int
    role: str  # "customer" | "assistant"
    content: str
    occurred_at: datetime
    governance: InboxGovernanceContext | None
    governance_decision_id: str | None


@dataclass(frozen=True, slots=True)
class InboxConversationSummaryRecord:
    session_id: str
    external_handle: str
    channel: str
    lifecycle_phase: str
    opened_at: datetime
    last_message_at: datetime | None
    message_count: int
    customer_identity_id: str | None
    has_governance_context: bool


@dataclass(frozen=True, slots=True)
class InboxConversationSummaryPage:
    items: tuple[InboxConversationSummaryRecord, ...]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True, slots=True)
class InboxThreadRecord:
    session_id: str
    external_handle: str
    channel: str
    lifecycle_phase: str
    opened_at: datetime
    customer_identity_id: str | None
    messages: tuple[InboxMessage, ...]


class InboxSessionNotFoundError(RuntimeError):
    """Raised when the requested session is absent or tenant-invisible."""


# ── Helpers ──────────────────────────────────────────────────────────────────


def _channel_from_session(session: SessionRecord) -> str:
    attrs: dict[str, Any] = dict(session.context_attributes or {})
    return str(attrs.get("source_channel") or "unknown")


def _content_from_payload(payload: dict[str, Any]) -> str:
    return str(
        payload.get("content")
        or payload.get("text")
        or payload.get("message")
        or ""
    )


# ── Service ──────────────────────────────────────────────────────────────────


class InboxService:
    """Read-only service that surfaces agent↔customer conversation threads."""

    def __init__(
        self,
        *,
        session_repo: SessionPersistenceProtocol,
        resolution_repo: PostgresResolutionProposalPersistence,
    ) -> None:
        self._session_repo = session_repo
        self._resolution_repo = resolution_repo

    async def list_conversations(
        self,
        *,
        expected_tenant_id: str,
        lifecycle_phase: SessionLifecyclePhase | None = None,
        channel: str | None = None,
        customer_identity_id: str | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> InboxConversationSummaryPage:
        session_page = await self._session_repo.list_sessions(
            SessionQuery(
                lifecycle_phase=lifecycle_phase,
                limit=limit,
                offset=offset,
            ),
            expected_tenant_id=expected_tenant_id,
        )

        items: list[InboxConversationSummaryRecord] = []
        for s in session_page.sessions:
            detected_channel = _channel_from_session(s)
            if channel and detected_channel != channel:
                continue
            if customer_identity_id and (
                s.customer_identity_id is None
                or str(s.customer_identity_id) != customer_identity_id
            ):
                continue

            events_page = await self._session_repo.list_events(
                SessionEventQuery(
                    session_id=s.session_id,
                    limit=200,
                    offset=0,
                ),
                expected_tenant_id=expected_tenant_id,
            )
            conv_events = [
                e for e in events_page.events if e.kind in _CONVERSATION_KINDS
            ]
            last_message_at: datetime | None = None
            if conv_events:
                last = max(conv_events, key=lambda e: e.sequence)
                last_message_at = last.occurred_at

            has_governance = any(
                e.governance_decision_id is not None
                for e in conv_events
                if e.kind == SessionEventKind.ASSISTANT_RESPONSE
            )

            items.append(
                InboxConversationSummaryRecord(
                    session_id=str(s.session_id),
                    external_handle=s.external_handle,
                    channel=detected_channel,
                    lifecycle_phase=s.lifecycle_phase.value,
                    opened_at=s.opened_at,
                    last_message_at=last_message_at,
                    message_count=len(conv_events),
                    customer_identity_id=(
                        str(s.customer_identity_id)
                        if s.customer_identity_id is not None
                        else None
                    ),
                    has_governance_context=has_governance,
                )
            )

        items.sort(
            key=lambda r: r.last_message_at or r.opened_at,
            reverse=True,
        )

        return InboxConversationSummaryPage(
            items=tuple(items),
            total=session_page.total,
            limit=limit,
            offset=offset,
        )

    async def get_thread(
        self,
        *,
        session_id: str,
        expected_tenant_id: str,
        include_siblings: bool = False,
    ) -> InboxThreadRecord:
        from uuid import UUID

        sid = SessionId(UUID(session_id))
        session = await self._session_repo.get_session(
            sid, expected_tenant_id=expected_tenant_id
        )
        if session is None:
            raise InboxSessionNotFoundError(f"session {session_id!r} not found")

        session_ids_to_fetch: list[str] = [session_id]

        if include_siblings and session.customer_identity_id is not None:
            sibling_page = await self._session_repo.list_sessions(
                SessionQuery(limit=50, offset=0),
                expected_tenant_id=expected_tenant_id,
            )
            for s in sibling_page.sessions:
                sid_str = str(s.session_id)
                if (
                    sid_str != session_id
                    and s.customer_identity_id == session.customer_identity_id
                ):
                    # Confirm-before-reveal: only MERGED cross-channel sessions
                    merge_state = str(
                        s.context_attributes.get("cross_channel_merge_state") or ""
                    )
                    if merge_state == "MERGED":
                        session_ids_to_fetch.append(sid_str)

        all_messages: list[InboxMessage] = []
        for sid_str in session_ids_to_fetch:
            from uuid import UUID as _UUID

            events_page = await self._session_repo.list_events(
                SessionEventQuery(
                    session_id=SessionId(_UUID(sid_str)),
                    limit=500,
                    offset=0,
                ),
                expected_tenant_id=expected_tenant_id,
            )
            conv_events = [
                e for e in events_page.events if e.kind in _CONVERSATION_KINDS
            ]
            if not conv_events:
                continue

            proposals_page = await self._resolution_repo.list_resolution_proposals(
                ResolutionProposalQuery(
                    session_id=sid_str,
                    limit=100,
                    offset=0,
                ),
                expected_tenant_id=expected_tenant_id,
            )
            gov_by_decision_id: dict[str, InboxGovernanceContext] = {
                str(p.governance_decision_id): InboxGovernanceContext(
                    proposal_id=str(p.proposal_id),
                    governance_verdict=p.governance_verdict.value,
                    autonomy_decision=p.autonomy_decision.value,
                    supervisor_verdict=p.supervisor_verdict.value,
                    status=p.status.value,
                    resolution_category=p.resolution_category,
                    confidence=p.confidence,
                    governance_decision_id=str(p.governance_decision_id),
                )
                for p in proposals_page.items
                if p.governance_decision_id is not None
            }

            for event in conv_events:
                governance: InboxGovernanceContext | None = None
                if (
                    event.kind == SessionEventKind.ASSISTANT_RESPONSE
                    and event.governance_decision_id is not None
                ):
                    governance = gov_by_decision_id.get(
                        str(event.governance_decision_id)
                    )
                all_messages.append(
                    InboxMessage(
                        event_id=str(event.event_id),
                        sequence=event.sequence,
                        role=(
                            "customer"
                            if event.kind == SessionEventKind.CUSTOMER_MESSAGE
                            else "assistant"
                        ),
                        content=_content_from_payload(dict(event.payload)),
                        occurred_at=event.occurred_at,
                        governance=governance,
                        governance_decision_id=(
                            str(event.governance_decision_id)
                            if event.governance_decision_id is not None
                            else None
                        ),
                    )
                )

        all_messages.sort(key=lambda m: m.sequence)

        return InboxThreadRecord(
            session_id=str(session.session_id),
            external_handle=session.external_handle,
            channel=_channel_from_session(session),
            lifecycle_phase=session.lifecycle_phase.value,
            opened_at=session.opened_at,
            customer_identity_id=(
                str(session.customer_identity_id)
                if session.customer_identity_id is not None
                else None
            ),
            messages=tuple(all_messages),
        )


def _parse_lifecycle_phase(raw: str) -> "SessionLifecyclePhase | None":
    try:
        return SessionLifecyclePhase(raw)
    except ValueError:
        return None


__all__ = [
    "InboxConversationSummaryPage",
    "InboxConversationSummaryRecord",
    "InboxGovernanceContext",
    "InboxMessage",
    "InboxService",
    "InboxSessionNotFoundError",
    "InboxThreadRecord",
    "_parse_lifecycle_phase",
]

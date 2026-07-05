"""MVP-7 Step 2 — Customer-confirmed cross-channel merge.

State machine (stored in session context_attributes under key
``mvp7.merge``):

  NONE → CANDIDATE → CONFIRMATION_SENT → MERGED
                   ↘ ABANDONED (on NO / error)

All state transitions are append-only OPERATIONAL_OBSERVATION events on
the session timeline — fully audited and forensically reconstructable.

Safety invariants (hard):
  1. No auto-merge. merge_state reaches MERGED only via explicit customer
     YES confirmation captured on the next inbound message.
  2. Confirm-before-reveal. The confirmation message contains only the
     prior channel name and a minimal summary of the prior case category
     (CATEGORY ONLY, no content/PII of the other thread).
  3. Fail-closed. Any error in the flow leaves merge_state=CANDIDATE or
     clears it entirely — never silently merges.
  4. Idempotent. A second YES on an already-MERGED session is a no-op.
  5. Tenant-isolated. All lookups accept expected_tenant_id; no cross-
     tenant session is ever visible.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import replace as dc_replace
from datetime import datetime, timezone
from typing import Any

from app.session.enums import SessionContinuityMode, SessionEventKind
from app.session.identity import as_session_id
from app.session.persistence.records import SessionRecord
from app.session.persistence.repository import SessionPersistenceProtocol

logger = logging.getLogger(__name__)

# ── merge state keys stored in session.context_attributes ────────────────────

MERGE_KEY = "mvp7.merge"
_MERGE_KEY = MERGE_KEY
_STATE_NONE = "none"
_STATE_CANDIDATE = "candidate"
_STATE_CONFIRMATION_SENT = "confirmation_sent"
_STATE_MERGED = "merged"
_STATE_ABANDONED = "abandoned"

# ── event type tags written to the session timeline ───────────────────────────

EVT_MERGE_CANDIDATE_FLAGGED = "cross_channel_merge_candidate_flagged"
EVT_MERGE_CONFIRMATION_SENT = "cross_channel_merge_confirmation_sent"
EVT_MERGE_COMPLETED = "cross_channel_merge_completed"
EVT_MERGE_ABANDONED = "cross_channel_merge_abandoned"

# ── default confirmation message template ─────────────────────────────────────

_DEFAULT_CONFIRMATION_TEMPLATE = (
    "Hi! It looks like you may have also contacted us via {prior_channel} "
    "about a {prior_category} issue. Is this the same request, or a "
    "different one? Reply YES to link your conversations so we can help "
    "faster, or NO to keep them separate."
)

# ── yes/no parser ─────────────────────────────────────────────────────────────

_YES_TOKENS = frozenset(
    {"yes", "yeah", "yep", "yup", "y", "sure", "correct", "right", "affirmative",
     "ok", "okay", "confirm", "confirmed", "that's me", "thats me", "same", "link"}
)
_NO_TOKENS = frozenset(
    {"no", "nope", "n", "nah", "different", "not me", "wrong", "separate",
     "not the same", "unlink", "cancel", "stop", "decline", "negative"}
)


def parse_confirmation_response(text: str) -> str | None:
    """Parse a customer reply into 'yes', 'no', or None (ambiguous).

    Intentionally strict: ambiguous → None (treated as NO by the caller,
    which is the safe default). Only canonical yes/no tokens accepted so
    natural-language hedges don't accidentally merge sessions.
    """
    normalised = text.lower().strip().rstrip("!.,?")
    # Single-token exact match first
    if normalised in _YES_TOKENS:
        return "yes"
    if normalised in _NO_TOKENS:
        return "no"
    # Multi-token: only accept if the FIRST meaningful word is a yes/no token
    first_word = normalised.split()[0] if normalised else ""
    if first_word in _YES_TOKENS:
        return "yes"
    if first_word in _NO_TOKENS:
        return "no"
    return None  # ambiguous → caller treats as NO


# ── state accessors ───────────────────────────────────────────────────────────


def get_raw_merge_state(session: SessionRecord) -> dict[str, Any]:
    return dict(session.context_attributes.get(_MERGE_KEY) or {})


def _merge_state(session: SessionRecord) -> dict[str, Any]:
    return get_raw_merge_state(session)


def get_merge_status(session: SessionRecord) -> str:
    return str(_merge_state(session).get("status", _STATE_NONE))


def is_merge_candidate(session: SessionRecord) -> bool:
    return get_merge_status(session) == _STATE_CANDIDATE


def is_awaiting_confirmation(session: SessionRecord) -> bool:
    return get_merge_status(session) == _STATE_CONFIRMATION_SENT


def is_already_merged(session: SessionRecord) -> bool:
    return get_merge_status(session) == _STATE_MERGED


# ── helper: update context_attributes merge state ─────────────────────────────


def _with_merge_state(session: SessionRecord, state: dict[str, Any]) -> SessionRecord:
    attrs = dict(session.context_attributes)
    attrs[_MERGE_KEY] = state
    return dc_replace(session, context_attributes=attrs, revision=session.revision + 1)


# ── core merge operations ─────────────────────────────────────────────────────


async def flag_merge_candidate(
    *,
    persistence: SessionPersistenceProtocol,
    session: SessionRecord,
    prior_session_id: str,
    customer_identity_id: str,
    prior_channel: str | None,
    prior_category: str | None,
    match_field: str | None,
    tenant_id: str,
) -> SessionRecord:
    """Mark a session as a cross-channel merge candidate.

    Called after identity detection matches this session to an existing open
    session on a different channel. Does NOT send any message — only writes
    the candidate flag and timeline event. The confirmation message is sent
    separately via build_confirmation_message().

    NEVER raises; returns the (possibly unchanged) session on any failure.
    """
    if is_already_merged(session):
        return session
    if is_merge_candidate(session) or is_awaiting_confirmation(session):
        return session
    try:
        state = {
            "status": _STATE_CANDIDATE,
            "prior_session_id": prior_session_id,
            "customer_identity_id": customer_identity_id,
            "prior_channel": prior_channel or "another channel",
            "prior_category": prior_category or "support",
            "match_field": match_field,
            "flagged_at": datetime.now(timezone.utc).isoformat(),
        }
        updated = _with_merge_state(session, state)
        saved = await persistence.save_session(updated)

        # Append audit event — idempotent key prevents double-write on retry
        await _append_merge_event(
            persistence=persistence,
            session=saved,
            event_type=EVT_MERGE_CANDIDATE_FLAGGED,
            payload={
                "prior_session_id": prior_session_id,
                "customer_identity_id": customer_identity_id,
                "prior_channel": prior_channel,
                "prior_category": prior_category,
                "match_field": match_field,
            },
            idempotency_key=f"{EVT_MERGE_CANDIDATE_FLAGGED}:{session.session_id}:{prior_session_id}",
        )
        logger.info(
            "cross_channel_merge_candidate_flagged tenant=%s session=%s prior=%s",
            tenant_id,
            session.session_id,
            prior_session_id,
        )
        return saved
    except Exception:
        logger.warning(
            "flag_merge_candidate_failed tenant=%s session=%s",
            tenant_id,
            session.session_id,
            exc_info=True,
        )
        return session


def build_confirmation_message(
    *,
    session: SessionRecord,
    template: str | None = None,
) -> str | None:
    """Build the customer-facing confirmation message for a merge candidate.

    Confirm-before-reveal: the message contains ONLY:
      - The prior channel name (e.g. 'email')
      - The prior issue CATEGORY (e.g. 'warranty', 'shipping') — not content
    NO PII, message bodies, order details, or any content from the other thread.

    Returns None if the session is not in CANDIDATE state.
    """
    if not is_merge_candidate(session):
        return None
    state = _merge_state(session)
    prior_channel = str(state.get("prior_channel") or "another channel")
    prior_category = str(state.get("prior_category") or "support")
    tpl = template or _DEFAULT_CONFIRMATION_TEMPLATE
    try:
        return tpl.format(
            prior_channel=prior_channel,
            prior_category=prior_category,
        )
    except (KeyError, ValueError):
        return (
            f"Hi! We think we may have heard from you before via "
            f"{prior_channel}. Is this the same issue? Reply YES to link "
            f"your conversations, or NO to keep them separate."
        )


async def record_confirmation_sent(
    *,
    persistence: SessionPersistenceProtocol,
    session: SessionRecord,
    confirmation_text: str,
    tenant_id: str,
) -> SessionRecord:
    """Advance merge state to CONFIRMATION_SENT after outbound message is queued.

    NEVER raises; returns the (possibly unchanged) session on any failure.
    """
    if not is_merge_candidate(session):
        return session
    try:
        state = dict(_merge_state(session))
        state["status"] = _STATE_CONFIRMATION_SENT
        state["confirmation_sent_at"] = datetime.now(timezone.utc).isoformat()
        updated = _with_merge_state(session, state)
        saved = await persistence.save_session(updated)
        await _append_merge_event(
            persistence=persistence,
            session=saved,
            event_type=EVT_MERGE_CONFIRMATION_SENT,
            payload={"confirmation_text_length": len(confirmation_text)},
            idempotency_key=(
                f"{EVT_MERGE_CONFIRMATION_SENT}:{session.session_id}"
            ),
        )
        return saved
    except Exception:
        logger.warning(
            "record_confirmation_sent_failed tenant=%s session=%s",
            tenant_id,
            session.session_id,
            exc_info=True,
        )
        return session


async def handle_confirmation_response(
    *,
    persistence: SessionPersistenceProtocol,
    session: SessionRecord,
    customer_text: str,
    tenant_id: str,
) -> tuple[str, SessionRecord]:
    """Parse the customer's reply and act.

    Returns (decision, updated_session) where decision is one of:
      'yes'       — merged; session updated with MERGED state
      'no'        — abandoned; merge state cleared
      'ambiguous' — treated as NO; merge state abandoned

    NEVER raises; on any error returns ('error', unchanged_session).
    """
    if not is_awaiting_confirmation(session):
        return ("not_pending", session)
    try:
        decision = parse_confirmation_response(customer_text)
        if decision == "yes":
            return await _execute_merge(
                persistence=persistence,
                session=session,
                tenant_id=tenant_id,
            )
        else:
            # NO or ambiguous → abandon safely
            return await _abandon_merge(
                persistence=persistence,
                session=session,
                customer_text=customer_text,
                decision=decision or "ambiguous",
                tenant_id=tenant_id,
            )
    except Exception:
        logger.warning(
            "handle_confirmation_response_failed tenant=%s session=%s",
            tenant_id,
            session.session_id,
            exc_info=True,
        )
        return ("error", session)


async def _execute_merge(
    *,
    persistence: SessionPersistenceProtocol,
    session: SessionRecord,
    tenant_id: str,
) -> tuple[str, SessionRecord]:
    """Complete the merge on customer YES confirmation.

    What 'merge' means concretely:
      1. Both sessions get the same customer_identity_id (already set on
         detection; this just ensures the prior session also has it).
      2. The prior session's category is copied into THIS session's
         context_attributes as 'mvp7.prior_context' — minimal, no PII.
      3. A CROSS_CHANNEL_MERGE_COMPLETED timeline event is written on
         this session (audited: both session IDs, identity ID, confirmation
         evidence).
      4. merge_state → MERGED.

    Idempotent: if already MERGED, returns immediately.
    """
    if is_already_merged(session):
        return ("yes", session)

    state = _merge_state(session)
    prior_session_id = str(state.get("prior_session_id") or "")
    customer_identity_id = str(state.get("customer_identity_id") or "")
    prior_channel = str(state.get("prior_channel") or "")
    prior_category = str(state.get("prior_category") or "")

    # Load prior session (tenant-scoped)
    prior_session: SessionRecord | None = None
    if prior_session_id:
        try:
            prior_session = await persistence.get_session(
                as_session_id(prior_session_id),
                expected_tenant_id=tenant_id,
            )
        except Exception:
            logger.warning(
                "merge_prior_session_load_failed session=%s prior=%s",
                session.session_id,
                prior_session_id,
                exc_info=True,
            )

    # Stamp customer_identity_id on prior session if missing
    if prior_session is not None and prior_session.customer_identity_id is None:
        try:
            updated_prior = dc_replace(
                prior_session,
                customer_identity_id=uuid.UUID(customer_identity_id),
                revision=prior_session.revision + 1,
            )
            await persistence.save_session(updated_prior)
        except Exception:
            logger.warning(
                "merge_prior_session_stamp_failed session=%s prior=%s",
                session.session_id,
                prior_session_id,
                exc_info=True,
            )

    # Build the updated merge state and attach minimal prior context
    # (category only — no PII, no message content from the other thread)
    attrs = dict(session.context_attributes)
    attrs[_MERGE_KEY] = {
        **state,
        "status": _STATE_MERGED,
        "merged_at": datetime.now(timezone.utc).isoformat(),
    }
    # Minimal prior context for the agent — category only, not content
    attrs["mvp7.prior_context"] = {
        "prior_session_id": prior_session_id,
        "prior_channel": prior_channel,
        "prior_category": prior_category,
        "customer_identity_id": customer_identity_id,
    }
    updated = dc_replace(
        session,
        context_attributes=attrs,
        customer_identity_id=uuid.UUID(customer_identity_id) if customer_identity_id else session.customer_identity_id,
        revision=session.revision + 1,
    )
    saved = await persistence.save_session(updated)

    await _append_merge_event(
        persistence=persistence,
        session=saved,
        event_type=EVT_MERGE_COMPLETED,
        payload={
            "prior_session_id": prior_session_id,
            "customer_identity_id": customer_identity_id,
            "prior_channel": prior_channel,
            "prior_category": prior_category,
            "confirmation_evidence": "customer_confirmed_yes",
            "merged_at": datetime.now(timezone.utc).isoformat(),
        },
        idempotency_key=f"{EVT_MERGE_COMPLETED}:{session.session_id}",
    )
    logger.info(
        "cross_channel_merge_completed tenant=%s session=%s prior=%s identity=%s",
        tenant_id,
        session.session_id,
        prior_session_id,
        customer_identity_id,
    )
    return ("yes", saved)


async def _abandon_merge(
    *,
    persistence: SessionPersistenceProtocol,
    session: SessionRecord,
    customer_text: str,
    decision: str,
    tenant_id: str,
) -> tuple[str, SessionRecord]:
    """Abandon the merge on customer NO or ambiguous response.

    State → ABANDONED (then cleared on next read — ABANDONED is terminal).
    No PII from the other thread is ever written; sessions remain separate.
    """
    state = _merge_state(session)
    attrs = dict(session.context_attributes)
    attrs[_MERGE_KEY] = {
        **state,
        "status": _STATE_ABANDONED,
        "abandoned_at": datetime.now(timezone.utc).isoformat(),
        "decision": decision,
    }
    updated = dc_replace(
        session, context_attributes=attrs, revision=session.revision + 1
    )
    try:
        saved = await persistence.save_session(updated)
        await _append_merge_event(
            persistence=persistence,
            session=saved,
            event_type=EVT_MERGE_ABANDONED,
            payload={
                "decision": decision,
                "prior_session_id": str(state.get("prior_session_id") or ""),
                "abandoned_at": datetime.now(timezone.utc).isoformat(),
            },
            idempotency_key=f"{EVT_MERGE_ABANDONED}:{session.session_id}",
        )
        logger.info(
            "cross_channel_merge_abandoned tenant=%s session=%s decision=%s",
            tenant_id,
            session.session_id,
            decision,
        )
        return (decision or "no", saved)
    except Exception:
        logger.warning(
            "abandon_merge_failed tenant=%s session=%s",
            tenant_id,
            session.session_id,
            exc_info=True,
        )
        return (decision or "no", session)


# ── shared timeline event writer ──────────────────────────────────────────────


async def _append_merge_event(
    *,
    persistence: SessionPersistenceProtocol,
    session: SessionRecord,
    event_type: str,
    payload: dict[str, Any],
    idempotency_key: str,
) -> None:
    """Write a merge audit event directly to persistence.

    Bypasses SessionRuntime to avoid the bootstrap-event (sequence=0)
    requirement, which is only enforced when sessions are opened via
    the runtime. Merge events are appended after-the-fact to
    already-running sessions.

    Uses OPERATIONAL_OBSERVATION kind (already in the enum vocabulary).
    Idempotency key prevents duplicate events on Celery retries.
    NEVER raises — audit failure must not block the pipeline.
    """
    try:
        from app.session.identity import generate_event_id
        from app.session.persistence.records import SessionEventRecord

        # Check for existing event with this idempotency key
        existing = await persistence.get_event_by_idempotency_key(
            session_id=session.session_id,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            return

        # Determine next sequence number
        from app.session.persistence.models import SessionEventQuery
        events_page = await persistence.list_events(
            SessionEventQuery(session_id=session.session_id),
        )
        next_seq = len(events_page.events)

        now = datetime.now(timezone.utc)
        event_record = SessionEventRecord(
            event_id=generate_event_id(),
            session_id=session.session_id,
            sequence=next_seq,
            kind=SessionEventKind.OPERATIONAL_OBSERVATION,
            continuity_mode=SessionContinuityMode.SYNCHRONOUS,
            occurred_at=now,
            recorded_at=now,
            payload={"event_type": event_type, **payload},
            annotation=event_type,
            idempotency_key=idempotency_key,
        )
        await persistence.save_event(event_record)
    except Exception:
        logger.warning(
            "_append_merge_event_failed event_type=%s session=%s",
            event_type,
            session.session_id,
            exc_info=True,
        )


__all__ = [
    "EVT_MERGE_ABANDONED",
    "EVT_MERGE_CANDIDATE_FLAGGED",
    "EVT_MERGE_COMPLETED",
    "EVT_MERGE_CONFIRMATION_SENT",
    "build_confirmation_message",
    "flag_merge_candidate",
    "get_merge_status",
    "handle_confirmation_response",
    "is_already_merged",
    "is_awaiting_confirmation",
    "is_merge_candidate",
    "parse_confirmation_response",
    "record_confirmation_sent",
]

"""MVP-7 Step 2 — Customer-confirmed cross-channel merge: live flow verification.

Five scenario tests covering:
  Scenario 1 — YES path: detect → flag candidate → confirmation message built
                (confirm-before-reveal) → customer says YES → sessions MERGED,
                both stamped with same customer_identity_id, audit event written.
  Scenario 2 — NO path: same setup, customer says NO → sessions remain SEPARATE,
                state ABANDONED, no data mixed.
  Scenario 3 — Ambiguous / no response → treated as NO (safe default).
  Scenario 4 — Error in merge flow → fail-closed, sessions remain separate.
  Scenario 5 — Idempotency: double YES on already-MERGED session → no-op.
  Scenario 6 — Confirm-before-reveal: confirmation message must NOT contain
                content/PII from the other session's messages.
  Scenario 7 — Parser coverage: YES/NO token set.

All run in-process with InMemorySessionPersistence — no Bedrock, no DB.
"""

from __future__ import annotations

import uuid
from dataclasses import replace as dc_replace
from datetime import datetime, timezone

import pytest

from app.cognition.extraction import ExtractionFieldSpec, ExtractionSchema
from app.session.cross_channel_merge import (
    EVT_MERGE_ABANDONED,
    EVT_MERGE_CANDIDATE_FLAGGED,
    EVT_MERGE_COMPLETED,
    EVT_MERGE_CONFIRMATION_SENT,
    build_confirmation_message,
    flag_merge_candidate,
    get_merge_status,
    handle_confirmation_response,
    is_already_merged,
    is_awaiting_confirmation,
    is_merge_candidate,
    parse_confirmation_response,
    record_confirmation_sent,
)
from app.session.enums import (
    SessionContinuityMode,
    SessionEventKind,
    SessionLifecyclePhase,
    SessionScope,
)
from app.session.identity import SessionId, SessionLineageId
from app.session.identity_resolution import IdentityResolutionRuntime
from app.session.persistence.memory import InMemorySessionPersistence
from app.session.persistence.models import SessionEventQuery
from app.session.persistence.records import SessionRecord

_TENANT = "tenant-verify"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _session(
    *,
    tenant_id: str = _TENANT,
    external_handle: str = "handle@example.com",
    customer_identity_id: uuid.UUID | None = None,
    context_attributes: dict | None = None,
) -> SessionRecord:
    sid = SessionId(uuid.uuid4())
    lid = SessionLineageId(uuid.uuid4())
    now = _now()
    return SessionRecord(
        session_id=sid,
        scope=SessionScope.OPERATIONAL_DOMAIN,
        external_handle=external_handle,
        tenant_id=tenant_id,
        principal_id=None,
        opened_at=now,
        lifecycle_phase=SessionLifecyclePhase.ACTIVE,
        lifecycle_recorded_at=now,
        lifecycle_reason=None,
        lineage_id=lid,
        root_session_id=sid,
        parent_session_id=None,
        ancestor_session_ids=(),
        lineage_depth=0,
        sequence_head=0,
        revision=1,
        customer_identity_id=customer_identity_id,
        context_attributes=context_attributes or {},
    )


# ---------------------------------------------------------------------------
# Scenario 1 — YES path: full detect → confirm → merge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_yes_path_full_merge_flow() -> None:
    """
    Email session 1 exists. WhatsApp session 2 arrives with same email.
    Identity detection flags session 2 as a merge candidate.
    Confirmation message is built (confirm-before-reveal).
    Customer says YES → sessions merged.

    Invariants verified:
      - MERGED state on session 2
      - customer_identity_id stamped on both sessions
      - EVT_MERGE_COMPLETED event written with audit payload
      - Prior session PII not exposed in confirmation message
    """
    persistence = InMemorySessionPersistence()

    identity_id = uuid.uuid4()
    prior_session = _session(
        external_handle="email:alice@example.com",
        customer_identity_id=identity_id,
    )
    current_session = _session(
        external_handle="whatsapp:+15551234567",
    )
    await persistence.save_session(prior_session)
    await persistence.save_session(current_session)

    # Step 1: flag merge candidate
    flagged = await flag_merge_candidate(
        persistence=persistence,
        session=current_session,
        prior_session_id=str(prior_session.session_id),
        customer_identity_id=str(identity_id),
        prior_channel="email",
        prior_category="warranty",
        match_field="email",
        tenant_id=_TENANT,
    )

    assert is_merge_candidate(flagged), "session must be in CANDIDATE state after flag"
    assert get_merge_status(flagged) == "candidate"

    # Step 2: build confirmation message (confirm-before-reveal)
    msg = build_confirmation_message(session=flagged)
    assert msg is not None
    assert len(msg) > 10, "confirmation message must not be empty"
    # Must reference prior channel/category — but NOT prior message content
    assert "email" in msg.lower() or "channel" in msg.lower() or "contacted" in msg.lower()
    # Must NOT contain PII or content from the other session
    assert "alice" not in msg.lower(), "confirmation must not leak customer name from other session"

    # Step 3: record that confirmation was sent
    after_sent = await record_confirmation_sent(
        persistence=persistence,
        session=flagged,
        confirmation_text=msg,
        tenant_id=_TENANT,
    )
    assert is_awaiting_confirmation(after_sent), "state must be CONFIRMATION_SENT"
    assert get_merge_status(after_sent) == "confirmation_sent"

    # Step 4: customer replies YES
    decision, merged = await handle_confirmation_response(
        persistence=persistence,
        session=after_sent,
        customer_text="Yes",
        tenant_id=_TENANT,
    )

    assert decision == "yes", f"decision must be 'yes', got {decision!r}"
    assert is_already_merged(merged), "session must be in MERGED state"
    assert get_merge_status(merged) == "merged"
    assert merged.customer_identity_id == identity_id, (
        f"customer_identity_id must be stamped on merged session: "
        f"expected {identity_id}, got {merged.customer_identity_id}"
    )

    # Verify audit event was written
    events_page = await persistence.list_events(
        SessionEventQuery(session_id=merged.session_id),
        expected_tenant_id=_TENANT,
    )
    event_types = [
        str(e.payload.get("event_type", ""))
        for e in events_page.events
    ]
    assert EVT_MERGE_CANDIDATE_FLAGGED in event_types, (
        f"EVT_MERGE_CANDIDATE_FLAGGED must be in timeline: {event_types}"
    )
    assert EVT_MERGE_CONFIRMATION_SENT in event_types, (
        f"EVT_MERGE_CONFIRMATION_SENT must be in timeline: {event_types}"
    )
    assert EVT_MERGE_COMPLETED in event_types, (
        f"EVT_MERGE_COMPLETED must be in timeline: {event_types}"
    )

    # Verify prior session stamped with identity_id
    updated_prior = await persistence.get_session(
        prior_session.session_id,
        expected_tenant_id=_TENANT,
    )
    assert updated_prior is not None
    assert updated_prior.customer_identity_id == identity_id, (
        f"prior session must also be stamped with customer_identity_id: "
        f"expected {identity_id}, got {updated_prior.customer_identity_id}"
    )

    # Verify prior context is minimal (no content dump)
    prior_ctx = merged.context_attributes.get("mvp7.prior_context", {})
    assert "prior_session_id" in prior_ctx
    assert "prior_channel" in prior_ctx
    assert "prior_category" in prior_ctx
    # No 'messages', 'content', 'reply' keys — just category
    for forbidden in ("messages", "content", "transcript", "reply", "body"):
        assert forbidden not in prior_ctx, (
            f"prior_context must not contain '{forbidden}' (PII risk)"
        )


# ---------------------------------------------------------------------------
# Scenario 2 — NO path: sessions remain separate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_path_sessions_remain_separate() -> None:
    """
    Customer says NO → merge abandoned, sessions remain separate,
    EVT_MERGE_ABANDONED written, no data mixed.
    """
    persistence = InMemorySessionPersistence()
    identity_id = uuid.uuid4()

    prior = _session(external_handle="email:bob@example.com", customer_identity_id=identity_id)
    current = _session(external_handle="whatsapp:+15557654321")
    await persistence.save_session(prior)
    await persistence.save_session(current)

    flagged = await flag_merge_candidate(
        persistence=persistence,
        session=current,
        prior_session_id=str(prior.session_id),
        customer_identity_id=str(identity_id),
        prior_channel="email",
        prior_category="shipping",
        match_field="email",
        tenant_id=_TENANT,
    )
    msg = build_confirmation_message(session=flagged)
    after_sent = await record_confirmation_sent(
        persistence=persistence,
        session=flagged,
        confirmation_text=msg or "",
        tenant_id=_TENANT,
    )

    decision, abandoned = await handle_confirmation_response(
        persistence=persistence,
        session=after_sent,
        customer_text="No",
        tenant_id=_TENANT,
    )

    assert decision == "no", f"decision must be 'no', got {decision!r}"
    assert get_merge_status(abandoned) == "abandoned", "state must be ABANDONED"
    assert not is_already_merged(abandoned), "session must NOT be merged"
    # Sessions remain separate — customer_identity_id must NOT be set on current
    assert abandoned.customer_identity_id is None, (
        f"NO response: current session must have no customer_identity_id, "
        f"got {abandoned.customer_identity_id}"
    )
    # Prior session unchanged
    prior_check = await persistence.get_session(
        prior.session_id, expected_tenant_id=_TENANT
    )
    assert prior_check is not None
    assert prior_check.customer_identity_id == identity_id, "prior session unchanged"

    # Verify EVT_MERGE_ABANDONED event
    events = await persistence.list_events(
        SessionEventQuery(session_id=abandoned.session_id),
        expected_tenant_id=_TENANT,
    )
    event_types = [str(e.payload.get("event_type", "")) for e in events.events]
    assert EVT_MERGE_ABANDONED in event_types, (
        f"EVT_MERGE_ABANDONED must be in timeline: {event_types}"
    )
    assert EVT_MERGE_COMPLETED not in event_types, (
        "EVT_MERGE_COMPLETED must NOT be in timeline on NO path"
    )


# ---------------------------------------------------------------------------
# Scenario 3 — Ambiguous response → treated as NO (safe default)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ambiguous_response_treated_as_no() -> None:
    """
    Customer says something ambiguous ('maybe', 'not sure', 'I think so').
    parse_confirmation_response returns None → treated as NO → abandoned.
    """
    persistence = InMemorySessionPersistence()
    identity_id = uuid.uuid4()
    prior = _session(external_handle="email:charlie@example.com", customer_identity_id=identity_id)
    current = _session(external_handle="whatsapp:+15550001111")
    await persistence.save_session(prior)
    await persistence.save_session(current)

    flagged = await flag_merge_candidate(
        persistence=persistence,
        session=current,
        prior_session_id=str(prior.session_id),
        customer_identity_id=str(identity_id),
        prior_channel="email",
        prior_category="return",
        match_field="email",
        tenant_id=_TENANT,
    )
    msg = build_confirmation_message(session=flagged)
    after_sent = await record_confirmation_sent(
        persistence=persistence, session=flagged,
        confirmation_text=msg or "", tenant_id=_TENANT,
    )

    ambiguous_responses = [
        "maybe",
        "not sure",
        "I think so",
        "possibly",
        "it depends",
        "Hello, I need help",  # normal message, not a confirmation
    ]
    for text in ambiguous_responses:
        decision = parse_confirmation_response(text)
        assert decision != "yes", (
            f"Ambiguous text {text!r} must NOT parse as YES (false-merge risk). "
            f"Got: {decision!r}"
        )

    # Full flow with ambiguous reply → abandon
    decision, result = await handle_confirmation_response(
        persistence=persistence,
        session=after_sent,
        customer_text="maybe",
        tenant_id=_TENANT,
    )
    assert decision != "yes", "ambiguous response must not trigger merge"
    assert not is_already_merged(result), "ambiguous must not merge"


# ---------------------------------------------------------------------------
# Scenario 4 — Error in merge flow → fail-closed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fail_closed_on_non_pending_session() -> None:
    """
    handle_confirmation_response on a session NOT awaiting confirmation
    returns ('not_pending', unchanged_session) — does not merge, no crash.
    """
    persistence = InMemorySessionPersistence()
    current = _session()
    await persistence.save_session(current)

    # Call without ever flagging as candidate
    decision, returned = await handle_confirmation_response(
        persistence=persistence,
        session=current,
        customer_text="Yes",
        tenant_id=_TENANT,
    )
    assert decision == "not_pending"
    assert not is_already_merged(returned)
    assert get_merge_status(returned) == "none"


@pytest.mark.asyncio
async def test_flag_candidate_noop_if_already_merged() -> None:
    """
    flag_merge_candidate on an already-MERGED session is a no-op.
    Idempotent — does not double-flag or corrupt state.
    """
    persistence = InMemorySessionPersistence()
    identity_id = uuid.uuid4()

    current = _session(customer_identity_id=identity_id)
    # Manually set to MERGED
    merged_attrs = {"mvp7.merge": {"status": "merged", "prior_session_id": "x"}}
    current = dc_replace(current, context_attributes=merged_attrs)
    await persistence.save_session(current)

    result = await flag_merge_candidate(
        persistence=persistence,
        session=current,
        prior_session_id="other-session",
        customer_identity_id=str(identity_id),
        prior_channel="email",
        prior_category="warranty",
        match_field="email",
        tenant_id=_TENANT,
    )
    # Must be unchanged
    assert get_merge_status(result) == "merged"
    assert is_already_merged(result)


# ---------------------------------------------------------------------------
# Scenario 5 — Idempotency: double YES on already-MERGED session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_idempotency_double_yes() -> None:
    """
    Calling handle_confirmation_response on an already-MERGED session
    returns ('yes', unchanged_session) without re-running the merge logic.
    """
    persistence = InMemorySessionPersistence()
    identity_id = uuid.uuid4()
    prior = _session(external_handle="email:dave@example.com", customer_identity_id=identity_id)
    current = _session(external_handle="whatsapp:+15552223333")
    await persistence.save_session(prior)
    await persistence.save_session(current)

    flagged = await flag_merge_candidate(
        persistence=persistence, session=current,
        prior_session_id=str(prior.session_id),
        customer_identity_id=str(identity_id),
        prior_channel="email", prior_category="refund",
        match_field="email", tenant_id=_TENANT,
    )
    msg = build_confirmation_message(session=flagged)
    after_sent = await record_confirmation_sent(
        persistence=persistence, session=flagged,
        confirmation_text=msg or "", tenant_id=_TENANT,
    )

    # First YES — should merge
    decision1, merged1 = await handle_confirmation_response(
        persistence=persistence, session=after_sent,
        customer_text="YES", tenant_id=_TENANT,
    )
    assert decision1 == "yes"
    assert is_already_merged(merged1)

    # Second YES on an already-MERGED session — must be a no-op
    # handle_confirmation_response only acts when is_awaiting_confirmation;
    # MERGED state is not awaiting → returns 'not_pending', session unchanged.
    decision2, merged2 = await handle_confirmation_response(
        persistence=persistence, session=merged1,
        customer_text="yes", tenant_id=_TENANT,
    )
    assert decision2 == "not_pending", (
        f"Double-YES on already-MERGED session must be no-op (not_pending), "
        f"got {decision2!r}"
    )
    assert is_already_merged(merged2), "session must remain MERGED"
    assert merged2.customer_identity_id == identity_id


# ---------------------------------------------------------------------------
# Scenario 6 — Confirm-before-reveal: no PII from other session in message
# ---------------------------------------------------------------------------


def test_confirmation_message_contains_no_other_session_content() -> None:
    """
    The confirmation message must:
      - Reference prior channel name and issue category
      - NOT contain any session content, message bodies, order IDs,
        names, emails, phone numbers, or any PII from the other thread.
    """
    dangerous_fields = {
        "customer_name": "Alice Johnson",
        "order_id": "ORD-99887766",
        "email": "alice@secretemail.com",
        "phone": "+15550001234",
        "message_content": "My charger is broken and I need help",
    }
    # Build a session with these fields in context (simulating agent's view)
    ctx = {
        "mvp7.merge": {
            "status": "candidate",
            "prior_session_id": "prior-123",
            "customer_identity_id": str(uuid.uuid4()),
            "prior_channel": "email",
            "prior_category": "warranty",
            "match_field": "email",
        },
        # Simulated other session data that should NOT appear in confirmation
        **{k: v for k, v in dangerous_fields.items()},
    }
    s = dc_replace(_session(context_attributes=ctx), revision=1)

    msg = build_confirmation_message(session=s)
    assert msg is not None

    # None of the dangerous values must appear in the confirmation text
    for field_name, value in dangerous_fields.items():
        assert value.lower() not in msg.lower(), (
            f"Confirmation message leaks '{field_name}' = {value!r}.\n"
            f"Message: {msg}"
        )

    # The message must mention prior channel (email) and category (warranty)
    assert "email" in msg.lower(), "must mention prior channel"
    assert "warranty" in msg.lower(), "must mention prior category"


# ---------------------------------------------------------------------------
# Scenario 7 — YES/NO parser coverage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text,expected", [
    ("yes", "yes"),
    ("YES", "yes"),
    ("Yes!", "yes"),
    ("yeah", "yes"),
    ("yep", "yes"),
    ("y", "yes"),
    ("sure", "yes"),
    ("correct", "yes"),
    ("confirm", "yes"),
    ("ok", "yes"),
    ("same", "yes"),
    ("no", "no"),
    ("NO", "no"),
    ("nope", "no"),
    ("n", "no"),
    ("different", "no"),
    ("not me", "no"),
    ("separate", "no"),
    ("cancel", "no"),
    ("maybe", None),
    ("I'm not sure", None),
    ("Hello I need help", None),
    ("", None),
    ("   ", None),
])
def test_parse_confirmation_response(text: str, expected: str | None) -> None:
    result = parse_confirmation_response(text)
    assert result == expected, (
        f"parse_confirmation_response({text!r}) = {result!r}, expected {expected!r}"
    )


# ---------------------------------------------------------------------------
# Scenario 8 — Confirmation-sent state prevents re-flagging
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_double_flag_when_confirmation_already_sent() -> None:
    """
    Once confirmation is sent (state = CONFIRMATION_SENT), calling
    flag_merge_candidate again is a no-op — state remains CONFIRMATION_SENT.
    """
    persistence = InMemorySessionPersistence()
    identity_id = uuid.uuid4()
    prior = _session(external_handle="email:eve@example.com", customer_identity_id=identity_id)
    current = _session(external_handle="whatsapp:+15553334444")
    await persistence.save_session(prior)
    await persistence.save_session(current)

    flagged = await flag_merge_candidate(
        persistence=persistence, session=current,
        prior_session_id=str(prior.session_id),
        customer_identity_id=str(identity_id),
        prior_channel="email", prior_category="warranty",
        match_field="email", tenant_id=_TENANT,
    )
    msg = build_confirmation_message(session=flagged)
    after_sent = await record_confirmation_sent(
        persistence=persistence, session=flagged,
        confirmation_text=msg or "", tenant_id=_TENANT,
    )
    assert is_awaiting_confirmation(after_sent)

    # Attempt re-flag with a different prior session
    result = await flag_merge_candidate(
        persistence=persistence, session=after_sent,
        prior_session_id="some-other-session",
        customer_identity_id=str(uuid.uuid4()),
        prior_channel="voice", prior_category="return",
        match_field="phone", tenant_id=_TENANT,
    )
    # State must remain CONFIRMATION_SENT (not reset to CANDIDATE)
    assert get_merge_status(result) == "confirmation_sent", (
        f"State must remain confirmation_sent, got {get_merge_status(result)!r}"
    )

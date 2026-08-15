"""Strict subtype recognition for timeline projection envelopes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.models.timeline import TimelineEvent
from app.session.enums import SessionContinuityMode, SessionEventKind
from app.session.identity import SessionEventId, SessionId
from app.session.models.timeline_event import SessionTimelineEvent

_SESSION_ID = SessionId(uuid.UUID("2e5a8e82-9184-520d-a027-6190977e6f4b"))
_NOW = datetime(2026, 8, 8, 9, 3, tzinfo=UTC)


def _event(*, annotation: str | None = "resolution_proposal_created", wrapper: object | None = None) -> SessionTimelineEvent:
    return SessionTimelineEvent(
        event_id=SessionEventId(uuid.uuid4()), session_id=_SESSION_ID, sequence=2,
        kind=SessionEventKind.OPERATIONAL_OBSERVATION,
        continuity_mode=SessionContinuityMode.DEFERRED,
        occurred_at=_NOW, recorded_at=_NOW,
        annotation=annotation,
        payload=(wrapper if wrapper is not None else _valid_wrapper()),  # type: ignore[arg-type]
    )


def _valid_wrapper() -> dict[str, object]:
    return {
        "session_id": str(_SESSION_ID), "dispatch_id": str(uuid.uuid4()),
        "tenant_id": "tenant-example", "event_type": "resolution_proposal_created",
        "timestamp": _NOW.isoformat(), "payload": {
            "proposal_id": str(uuid.uuid4()), "status": "pending_human_approval",
            "proposed_customer_reply": "Held for review.",
            "resolution_category": "device_damage", "confidence": 0.9,
            "autonomy_decision": "needs_human_approval",
            "supervisor_verdict": "needs_human_review",
            "governance_verdict": "require_approval",
            "recommended_actions": [], "evidence": [],
        },
    }


def test_valid_canonical_resolution_envelope_projects_required_trace_fields() -> None:
    projected = TimelineEvent.from_session_event(_event())
    assert projected.event_type == "resolution_proposal_created"
    assert projected.payload["status"] == "pending_human_approval"
    assert projected.payload["proposal_id"]
    assert projected.payload["proposed_customer_reply"] == "Held for review."
    assert projected.payload["recommended_actions"] == []


@pytest.mark.parametrize("annotation,mutator", [
    (None, lambda value: value),
    ("other", lambda value: value),
    ("resolution_proposal_created", lambda value: {**value, "event_type": "unknown"}),
    ("resolution_proposal_created", lambda value: {**value, "payload": None}),
    ("resolution_proposal_created", lambda value: {**value, "payload": {"status": "pending_human_approval"}}),
    ("resolution_proposal_created", lambda value: {**value, "session_id": "wrong"}),
])
def test_malformed_or_conflicting_envelopes_remain_operational_observations(annotation, mutator) -> None:  # type: ignore[no-untyped-def]
    projected = TimelineEvent.from_session_event(_event(annotation=annotation, wrapper=mutator(_valid_wrapper())))
    assert projected.event_type == "operational_observation"


def test_arbitrary_embedded_known_type_cannot_override_outer_observation() -> None:
    wrapper = _valid_wrapper()
    wrapper["event_type"] = "session_opened"
    projected = TimelineEvent.from_session_event(_event(annotation="session_opened", wrapper=wrapper))
    assert projected.event_type == "operational_observation"


def test_plain_operational_observation_is_unchanged() -> None:
    event = _event(annotation=None, wrapper={"arbitrary": "metadata"})
    projected = TimelineEvent.from_session_event(event)
    assert projected.event_type == "operational_observation"
    assert projected.payload == {"arbitrary": "metadata"}

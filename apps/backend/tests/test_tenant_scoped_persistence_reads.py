"""Phase 2.75-ε regression tests — tenant-scoped persistence reads.

Constitutional guarantee: persisted records belonging to a tenant
T MUST be invisible from any tenant T' ≠ T when the read API is
called with ``expected_tenant_id=T'``. The fields exist (row exists
in storage), but the read returns ``None`` (or empty collection)
to the requesting tenant — indistinguishable from "row not found".
This is row-level isolation; it prevents an authenticated tenant
from inferring the existence of another tenant's records by
ID-collision probing.

The check is opt-in (``expected_tenant_id`` defaults to ``None``)
so substrate-internal reads (reconstructors, persistence-level
joins) can span tenants when constitutionally legitimate. The
composition root pins ``expected_tenant_id`` at every public read.

Two surfaces are covered:

1. **Point reads** (``get_session``, ``get_event``,
   ``get_correlation``, ``get_envelope``, ``get_inspection``,
   ``get_findings_for_inspection``,
   ``get_evaluations_for_inspection``,
   ``get_escalations_for_inspection``) — Wedge 2.75-ε.
2. **Query / list reads** (``list_sessions``, ``list_events``,
   ``list_correlations``, ``query_envelopes``,
   ``query_inspections``) — Wedge 2.75-ε (extended) which
   closes the coordination-correlation-lookup gap. The
   ``expected_tenant_id`` parameter is the **outer** bound that
   precedes the caller's filter; callers cannot widen the scope.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.coordination.contracts.messages import CoordinationMessage
from app.coordination.envelopes import CoordinationEnvelope
from app.coordination.enums import (
    CoordinationDirection,
    CoordinationMessageType,
    CoordinationPriority,
    CoordinationStatus,
)
from app.coordination.identity import (
    derive_coordination_id,
    derive_message_id,
)
from app.coordination.models.payload import CoordinationPayload
from app.coordination.models.recipients import CoordinationRecipient
from app.coordination.persistence.memory import (
    InMemoryCoordinationPersistence,
)
from app.coordination.persistence.serializers import envelope_to_record
from app.session.enums import (
    SessionContinuityMode,
    SessionCorrelationKind,
    SessionEventKind,
    SessionLifecyclePhase,
    SessionScope,
)
from app.session.identity import (
    SessionCorrelationId,
    SessionId,
    SessionLineageId,
    derive_event_id,
)
from app.session.persistence.memory import InMemorySessionPersistence
from app.session.persistence.records import (
    SessionCorrelationRecord,
    SessionEventRecord,
    SessionRecord,
)
from app.supervisor.enums import (
    EvaluationStatus,
    FindingCategory,
    FindingSeverity,
    InspectionMode,
    SupervisorDecisionKind,
)
from app.supervisor.persistence.memory import InMemorySupervisorRepository
from app.supervisor.persistence.records import (
    EscalationDecisionRecord,
    EvaluationEvidenceRecord,
    InspectionRecord,
    QAEvaluationRecord,
    RuntimeFindingRecord,
    SupervisorDecisionRecord,
)


# ─── SESSION ────────────────────────────────────────────────────────


_NOW = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _session_record(
    *, session_id: SessionId, tenant: str | None
) -> SessionRecord:
    return SessionRecord(
        session_id=session_id,
        scope=SessionScope.TENANT,
        external_handle="ext",
        tenant_id=tenant,
        principal_id=None,
        opened_at=_NOW,
        lifecycle_phase=SessionLifecyclePhase.INITIATED,
        lifecycle_recorded_at=_NOW,
        lifecycle_reason=None,
        lineage_id=SessionLineageId(uuid.uuid4()),
        root_session_id=session_id,
        parent_session_id=None,
        ancestor_session_ids=(),
        lineage_depth=0,
        sequence_head=-1,
        revision=1,
    )


def _session_event(*, session_id: SessionId) -> SessionEventRecord:
    return SessionEventRecord(
        event_id=derive_event_id(session_id=session_id, sequence=0),
        session_id=session_id,
        sequence=0,
        kind=SessionEventKind.SESSION_OPENED,
        continuity_mode=SessionContinuityMode.SYNCHRONOUS,
        occurred_at=_NOW,
        recorded_at=_NOW,
    )


def _session_correlation(
    *, session_id: SessionId
) -> SessionCorrelationRecord:
    return SessionCorrelationRecord(
        correlation_id=SessionCorrelationId(uuid.uuid4()),
        session_id=session_id,
        kind=SessionCorrelationKind.COORDINATION,
        external_id="ext-corr",
        recorded_at=_NOW,
    )


@pytest.mark.asyncio
async def test_session_read_returns_none_for_cross_tenant() -> None:
    persistence = InMemorySessionPersistence()
    record = _session_record(
        session_id=SessionId(uuid.uuid4()), tenant="tenant-A"
    )
    await persistence.save_session(record)

    assert (
        await persistence.get_session(
            record.session_id, expected_tenant_id="tenant-A"
        )
        is record
    )
    assert (
        await persistence.get_session(
            record.session_id, expected_tenant_id="tenant-B"
        )
        is None
    )


@pytest.mark.asyncio
async def test_session_read_unscoped_returns_record() -> None:
    """Substrate-internal reads (no expected_tenant_id) still
    return the row — backward-compatible non-strict semantics."""
    persistence = InMemorySessionPersistence()
    record = _session_record(
        session_id=SessionId(uuid.uuid4()), tenant="tenant-A"
    )
    await persistence.save_session(record)
    assert await persistence.get_session(record.session_id) is record


@pytest.mark.asyncio
async def test_session_event_inherits_tenant_scope() -> None:
    persistence = InMemorySessionPersistence()
    sid = SessionId(uuid.uuid4())
    await persistence.save_session(
        _session_record(session_id=sid, tenant="tenant-A")
    )
    event = _session_event(session_id=sid)
    await persistence.save_event(event)

    assert (
        await persistence.get_event(
            event.event_id, expected_tenant_id="tenant-A"
        )
        is event
    )
    assert (
        await persistence.get_event(
            event.event_id, expected_tenant_id="tenant-B"
        )
        is None
    )


@pytest.mark.asyncio
async def test_session_correlation_inherits_tenant_scope() -> None:
    persistence = InMemorySessionPersistence()
    sid = SessionId(uuid.uuid4())
    await persistence.save_session(
        _session_record(session_id=sid, tenant="tenant-A")
    )
    correlation = _session_correlation(session_id=sid)
    await persistence.save_correlation(correlation)

    assert (
        await persistence.get_correlation(
            correlation.correlation_id,
            expected_tenant_id="tenant-A",
        )
        is correlation
    )
    assert (
        await persistence.get_correlation(
            correlation.correlation_id,
            expected_tenant_id="tenant-B",
        )
        is None
    )


# ─── COORDINATION ───────────────────────────────────────────────────


def _coord_envelope(*, tenant: str | None) -> CoordinationEnvelope:
    return CoordinationEnvelope(
        coordination_id=derive_coordination_id(seed="coord:1"),
        message=CoordinationMessage(
            message_id=derive_message_id(seed="msg:1"),
            message_type=CoordinationMessageType.HANDOFF,
            sender_id="agent:s",
            recipient=CoordinationRecipient(
                recipient_id="agent:r",
                kind="agent",
                tenant_id=tenant,
            ),
            payload=CoordinationPayload(
                content_type="x/x",
                body={},
                schema_version="1",
            ),
            priority=CoordinationPriority.NORMAL,
            in_reply_to=None,
            created_at=_NOW,
        ),
        direction=CoordinationDirection.AGENT_TO_AGENT,
        status=CoordinationStatus.DISPATCHED,
        sequence=1,
        runtime_instance_id=uuid.UUID(
            "00000000-0000-0000-0000-000000000aaa"
        ),
        correlation_id=None,
        parent_coordination_id=None,
        parent_message_id=None,
        request_id=None,
        tenant_id=tenant,
        governance_decision_id=None,
        governance_chain_id=None,
        created_at=_NOW,
        dispatched_at=_NOW,
    )


@pytest.mark.asyncio
async def test_coordination_envelope_isolates_by_tenant() -> None:
    persistence = InMemoryCoordinationPersistence()
    record = envelope_to_record(_coord_envelope(tenant="tenant-A"))
    await persistence.record_envelope(record)

    assert (
        await persistence.get_envelope(
            record.coordination_id, expected_tenant_id="tenant-A"
        )
        is record
    )
    assert (
        await persistence.get_envelope(
            record.coordination_id, expected_tenant_id="tenant-B"
        )
        is None
    )
    # Unscoped read still returns the row.
    assert (
        await persistence.get_envelope(record.coordination_id)
        is record
    )


# ─── SUPERVISOR ─────────────────────────────────────────────────────


def _make_inspection(
    *, inspection_id: str, tenant: str | None
) -> tuple[
    InspectionRecord,
    RuntimeFindingRecord,
    QAEvaluationRecord,
    EscalationDecisionRecord,
]:
    decision = SupervisorDecisionRecord(
        decision_id="dec:1",
        kind=SupervisorDecisionKind.ESCALATE.value,
        aggregate_score=0.5,
        finding_ids=("find:1",),
        escalation_ids=("esc:1",),
        reason="r",
        decided_at=_NOW.isoformat(),
    )
    inspection = InspectionRecord(
        inspection_id=inspection_id,
        execution_id="exec:1",
        runtime_instance_id="rt:1",
        correlation_id=None,
        request_id=None,
        tenant_id=tenant,
        inspection_mode=InspectionMode.LIVE.value,
        decision=decision,
        evaluator_names=("ev",),
        started_at=_NOW.isoformat(),
        ended_at=_NOW.isoformat(),
        latency_ms=0.0,
    )
    finding = RuntimeFindingRecord(
        finding_id="find:1",
        evaluator_name="ev",
        category=FindingCategory.OTHER.value,
        severity=FindingSeverity.HIGH.value,
        code="x.test",
        message="m",
        evidence=EvaluationEvidenceRecord(execution_id="exec:1"),
        detected_at=_NOW.isoformat(),
        metadata={"inspection_id": inspection_id},
    )
    evaluation = QAEvaluationRecord(
        inspection_id=inspection_id,
        evaluator_name="ev",
        status=EvaluationStatus.PASSED.value,
        score=1.0,
        finding_ids=("find:1",),
        started_at=_NOW.isoformat(),
        ended_at=_NOW.isoformat(),
        latency_ms=0.0,
    )
    escalation = EscalationDecisionRecord(
        escalation_id="esc:1",
        inspection_id=inspection_id,
        decision_id="dec:1",
        level="L2",
        reason="r",
        triggering_finding_ids=("find:1",),
        decided_at=_NOW.isoformat(),
    )
    return inspection, finding, evaluation, escalation


@pytest.mark.asyncio
async def test_supervisor_inspection_isolates_by_tenant() -> None:
    repo = InMemorySupervisorRepository()
    inspection, _, _, _ = _make_inspection(
        inspection_id="i:1", tenant="tenant-A"
    )
    await repo.record_inspection(inspection)

    assert (
        await repo.get_inspection(
            "i:1", expected_tenant_id="tenant-A"
        )
        is inspection
    )
    assert (
        await repo.get_inspection(
            "i:1", expected_tenant_id="tenant-B"
        )
        is None
    )
    assert (
        await repo.get_inspection("i:1") is inspection
    )  # unscoped path still returns


@pytest.mark.asyncio
async def test_supervisor_subrecords_inherit_tenant_scope() -> None:
    repo = InMemorySupervisorRepository()
    inspection, finding, evaluation, escalation = _make_inspection(
        inspection_id="i:1", tenant="tenant-A"
    )
    await repo.record_inspection(inspection)
    await repo.record_finding(finding)
    await repo.record_evaluation(evaluation)
    await repo.record_escalation(escalation)

    assert await repo.get_findings_for_inspection(
        "i:1", expected_tenant_id="tenant-A"
    ) == (finding,)
    assert (
        await repo.get_findings_for_inspection(
            "i:1", expected_tenant_id="tenant-B"
        )
        == ()
    )

    assert await repo.get_evaluations_for_inspection(
        "i:1", expected_tenant_id="tenant-A"
    ) == (evaluation,)
    assert (
        await repo.get_evaluations_for_inspection(
            "i:1", expected_tenant_id="tenant-B"
        )
        == ()
    )

    assert await repo.get_escalations_for_inspection(
        "i:1", expected_tenant_id="tenant-A"
    ) == (escalation,)
    assert (
        await repo.get_escalations_for_inspection(
            "i:1", expected_tenant_id="tenant-B"
        )
        == ()
    )


# ─── COMPOSITION-ROOT CONTRACT ──────────────────────────────────────


@pytest.mark.asyncio
async def test_session_runtime_get_session_enforces_scope() -> None:
    """End-to-end through SessionRuntime.get_session — proves the
    runtime forwards ``expected_tenant_id`` into persistence and
    folds the failure onto a never-raising envelope."""
    from app.session.runtime.runtime import SessionRuntime

    persistence = InMemorySessionPersistence()
    sid = SessionId(uuid.uuid4())
    await persistence.save_session(
        _session_record(session_id=sid, tenant="tenant-A")
    )
    runtime = SessionRuntime(persistence=persistence)

    same = await runtime.get_session(sid, expected_tenant_id="tenant-A")
    assert same.is_ok

    cross = await runtime.get_session(sid, expected_tenant_id="tenant-B")
    assert cross.result is None
    assert cross.error is not None


# ─── QUERY / LIST SURFACE (Wedge 2.75-ε extended, B2) ───────────────


@pytest.mark.asyncio
async def test_session_list_sessions_clamps_to_tenant() -> None:
    from app.session.persistence.models import SessionQuery

    persistence = InMemorySessionPersistence()
    sid_a = SessionId(uuid.uuid4())
    sid_b = SessionId(uuid.uuid4())
    await persistence.save_session(
        _session_record(session_id=sid_a, tenant="tenant-A")
    )
    await persistence.save_session(
        _session_record(session_id=sid_b, tenant="tenant-B")
    )

    page = await persistence.list_sessions(
        SessionQuery(), expected_tenant_id="tenant-A"
    )
    assert tuple(s.session_id for s in page.sessions) == (sid_a,)

    # Caller-supplied query.tenant_id is intersected with the
    # system bound; disagreeing values yield an empty page.
    page_xor = await persistence.list_sessions(
        SessionQuery(tenant_id="tenant-B"),
        expected_tenant_id="tenant-A",
    )
    assert page_xor.sessions == ()


@pytest.mark.asyncio
async def test_session_list_events_clamps_to_tenant() -> None:
    from app.session.persistence.models import SessionEventQuery

    persistence = InMemorySessionPersistence()
    sid = SessionId(uuid.uuid4())
    await persistence.save_session(
        _session_record(session_id=sid, tenant="tenant-A")
    )
    event = _session_event(session_id=sid)
    await persistence.save_event(event)

    same = await persistence.list_events(
        SessionEventQuery(session_id=sid),
        expected_tenant_id="tenant-A",
    )
    assert tuple(e.event_id for e in same.events) == (event.event_id,)
    cross = await persistence.list_events(
        SessionEventQuery(session_id=sid),
        expected_tenant_id="tenant-B",
    )
    assert cross.events == ()


@pytest.mark.asyncio
async def test_session_list_correlations_clamps_to_tenant() -> None:
    from app.session.persistence.models import (
        SessionCorrelationQuery,
    )

    persistence = InMemorySessionPersistence()
    sid = SessionId(uuid.uuid4())
    await persistence.save_session(
        _session_record(session_id=sid, tenant="tenant-A")
    )
    correlation = _session_correlation(session_id=sid)
    await persistence.save_correlation(correlation)

    same = await persistence.list_correlations(
        SessionCorrelationQuery(session_id=sid),
        expected_tenant_id="tenant-A",
    )
    assert tuple(c.correlation_id for c in same.correlations) == (
        correlation.correlation_id,
    )
    cross = await persistence.list_correlations(
        SessionCorrelationQuery(session_id=sid),
        expected_tenant_id="tenant-B",
    )
    assert cross.correlations == ()


@pytest.mark.asyncio
async def test_coordination_query_envelopes_clamps_to_tenant() -> None:
    """Closes the coordination-correlation-lookup gap. Coordination
    correlations live on the envelope record — so the envelope
    query path IS the correlation lookup path."""
    from app.coordination.persistence.models import CoordinationQuery

    persistence = InMemoryCoordinationPersistence()
    record = envelope_to_record(_coord_envelope(tenant="tenant-A"))
    await persistence.record_envelope(record)

    same = await persistence.query_envelopes(
        CoordinationQuery(), expected_tenant_id="tenant-A"
    )
    assert tuple(r.coordination_id for r in same.items) == (
        record.coordination_id,
    )
    cross = await persistence.query_envelopes(
        CoordinationQuery(), expected_tenant_id="tenant-B"
    )
    assert cross.items == ()


def test_coordination_runtime_list_messages_exposes_scope_parameter() -> (
    None
):
    """The runtime-level list API is the public read surface;
    composition root pins ``expected_tenant_id`` here. We assert
    the parameter is declared on the public method so callers
    can rely on it (the persistence-level test already proves
    enforcement)."""
    import inspect

    from app.coordination.runtime.runtime import CoordinationRuntime

    sig = inspect.signature(CoordinationRuntime.list_messages)
    assert "expected_tenant_id" in sig.parameters
    assert (
        sig.parameters["expected_tenant_id"].kind
        is inspect.Parameter.KEYWORD_ONLY
    )
    assert sig.parameters["expected_tenant_id"].default is None


@pytest.mark.asyncio
async def test_supervisor_query_inspections_clamps_to_tenant() -> None:
    from app.supervisor.persistence.models import InspectionQuery

    repo = InMemorySupervisorRepository()
    inspection, _, _, _ = _make_inspection(
        inspection_id="i:1", tenant="tenant-A"
    )
    await repo.record_inspection(inspection)

    same = await repo.query_inspections(
        InspectionQuery(), expected_tenant_id="tenant-A"
    )
    assert tuple(i.inspection_id for i in same.items) == (
        inspection.inspection_id,
    )
    cross = await repo.query_inspections(
        InspectionQuery(), expected_tenant_id="tenant-B"
    )
    assert cross.items == ()


@pytest.mark.asyncio
async def test_query_clamp_is_strict_outer_bound() -> None:
    """``expected_tenant_id`` is the outer bound; the caller's
    ``query.tenant_id`` filter is a strict inner subset. Setting
    the caller filter to a DIFFERENT tenant cannot widen the
    scope back."""
    from app.session.persistence.models import SessionQuery

    persistence = InMemorySessionPersistence()
    await persistence.save_session(
        _session_record(
            session_id=SessionId(uuid.uuid4()), tenant="tenant-A"
        )
    )
    await persistence.save_session(
        _session_record(
            session_id=SessionId(uuid.uuid4()), tenant="tenant-B"
        )
    )

    page = await persistence.list_sessions(
        SessionQuery(tenant_id="tenant-B"),
        expected_tenant_id="tenant-A",
    )
    assert page.sessions == ()
    page2 = await persistence.list_sessions(
        SessionQuery(tenant_id="tenant-A"),
        expected_tenant_id="tenant-A",
    )
    assert len(page2.sessions) == 1

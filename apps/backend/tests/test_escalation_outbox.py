"""Phase G escalation outbox recovery coverage."""

from __future__ import annotations

import uuid
import logging
from datetime import datetime, timedelta, timezone

import pytest

from app.dependencies.services import EscalationOutboxPublishError
from app.dependencies.services import (
    _DeferredEscalationPublisher,  # pyright: ignore[reportPrivateUsage]
)
from app.escalation import (
    EscalationAgentRuntime,
    EscalationOutboxStatus,
    EscalationPersistenceError,
    InMemoryEscalationPersistence,
)
from app.governance.persistence import (
    GovernanceDecisionRecord,
    InMemoryGovernanceRepository,
)
from app.session.enums import SessionLifecyclePhase, SessionScope
from app.session.identity import SessionId, SessionLineageId
from app.session.persistence import InMemorySessionPersistence, SessionRecord

_TENANT = "tenant-phase-g"
_SESSION_ID = "00000000-0000-0000-0000-00000000f001"
_DENY_ID = "00000000-0000-0000-0000-00000000f002"
_NOW = datetime(2026, 5, 23, 8, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_prepare_creates_escalation_outbox_record() -> None:
    runtime, store = await _runtime()

    prepared = await runtime.prepare_governance_denial_outbox(
        governance_decision_id=_DENY_ID,
        expected_tenant_id=_TENANT,
    )

    assert prepared.outbox.status is EscalationOutboxStatus.PENDING
    assert prepared.outbox.escalation_id == prepared.escalation.escalation_id
    assert prepared.outbox.tenant_id == _TENANT
    assert prepared.outbox.metadata["governance_decision_id"] == _DENY_ID
    assert await store.get_escalation_outbox_by_escalation(
        prepared.escalation.escalation_id,
        expected_tenant_id=_TENANT,
    ) == prepared.outbox


@pytest.mark.asyncio
async def test_escalation_outbox_claim_publish_and_fail_require_claim_id() -> None:
    runtime, _store = await _runtime()
    prepared = await runtime.prepare_governance_denial_outbox(
        governance_decision_id=_DENY_ID,
        expected_tenant_id=_TENANT,
    )

    claim = await runtime.claim_outbox_for_escalation(
        escalation_id=prepared.escalation.escalation_id,
        publisher_id="test:publisher-a",
        expected_tenant_id=_TENANT,
    )

    assert claim.claimed is True
    assert claim.outbox is not None
    assert claim.outbox.claim_id is not None
    assert claim.outbox.status is EscalationOutboxStatus.PUBLISHING
    with pytest.raises(EscalationPersistenceError, match="claim"):
        await runtime.mark_outbox_published(
            outbox_id=claim.outbox.outbox_id,
            claim_id="00000000-0000-0000-0000-00000000dead",
            expected_tenant_id=_TENANT,
        )

    published = await runtime.mark_outbox_published(
        outbox_id=claim.outbox.outbox_id,
        claim_id=claim.outbox.claim_id,
        expected_tenant_id=_TENANT,
    )
    assert published.status is EscalationOutboxStatus.PUBLISHED
    assert published.claim_id == claim.outbox.claim_id

    other_runtime, _other_store = await _runtime()
    other_prepared = await other_runtime.prepare_governance_denial_outbox(
        governance_decision_id=_DENY_ID,
        expected_tenant_id=_TENANT,
    )
    other_claim = await other_runtime.claim_outbox_for_escalation(
        escalation_id=other_prepared.escalation.escalation_id,
        publisher_id="test:publisher-b",
        expected_tenant_id=_TENANT,
    )
    assert other_claim.outbox is not None
    assert other_claim.outbox.claim_id is not None
    failed = await other_runtime.mark_outbox_failed(
        outbox_id=other_claim.outbox.outbox_id,
        claim_id=other_claim.outbox.claim_id,
        error="publish transport failed",
        expected_tenant_id=_TENANT,
    )
    assert failed.status is EscalationOutboxStatus.FAILED
    assert failed.last_error == "publish transport failed"


@pytest.mark.asyncio
async def test_escalation_outbox_recovers_stuck_publish(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    runtime, store = await _runtime()
    escalation = await runtime.create_for_governance_denial(
        governance_decision_id=_DENY_ID,
        expected_tenant_id=_TENANT,
    )
    outbox = await runtime.ensure_outbox_for_escalation(
        escalation,
        expected_tenant_id=_TENANT,
    )

    claim = await runtime.claim_outbox_for_escalation(
        escalation_id=escalation.escalation_id,
        publisher_id="test:publisher-a",
        expected_tenant_id=_TENANT,
    )
    assert claim.claimed is True
    assert claim.outbox is not None
    assert claim.outbox.claim_id is not None
    assert claim.outbox.status is EscalationOutboxStatus.PUBLISHING

    sweep = await runtime.reconcile_stale_outbox_records(
        stale_before=datetime.now(timezone.utc) + timedelta(seconds=1),
        expected_tenant_id=_TENANT,
    )

    assert len(sweep.requeued) == 1
    recovered = sweep.requeued[0]
    assert recovered.outbox_id == outbox.outbox_id
    assert recovered.status is EscalationOutboxStatus.PENDING
    assert recovered.claimed_at is None
    assert recovered.claim_id is None
    assert recovered.last_error == "stale_publishing_claim"
    assert "stale_escalation_outbox_requeued" in caplog.text

    reclaimed = await runtime.claim_outbox_for_escalation(
        escalation_id=escalation.escalation_id,
        publisher_id="test:publisher-b",
        expected_tenant_id=_TENANT,
    )
    assert reclaimed.claimed is True
    assert reclaimed.outbox is not None
    assert reclaimed.outbox.republish_count == 2
    assert reclaimed.outbox.claim_id != claim.outbox.claim_id
    assert await store.get_escalation_outbox_by_escalation(
        escalation.escalation_id,
        expected_tenant_id=_TENANT,
    ) == reclaimed.outbox


@pytest.mark.asyncio
async def test_crash_after_publish_before_mark_published_requeues() -> None:
    runtime, _store = await _runtime()
    prepared = await runtime.prepare_governance_denial_outbox(
        governance_decision_id=_DENY_ID,
        expected_tenant_id=_TENANT,
    )
    first = await runtime.claim_outbox_for_escalation(
        escalation_id=prepared.escalation.escalation_id,
        publisher_id="test:publisher-before-crash",
        expected_tenant_id=_TENANT,
    )
    assert first.claimed is True
    assert first.outbox is not None

    sweep = await runtime.reconcile_stale_outbox_records(
        stale_before=datetime.now(timezone.utc) + timedelta(seconds=1),
        expected_tenant_id=_TENANT,
    )
    second = await runtime.claim_outbox_for_escalation(
        escalation_id=prepared.escalation.escalation_id,
        publisher_id="test:publisher-after-crash",
        expected_tenant_id=_TENANT,
    )

    assert [row.outbox_id for row in sweep.requeued] == [first.outbox.outbox_id]
    assert second.claimed is True
    assert second.outbox is not None
    assert second.outbox.republish_count == 2
    assert second.outbox.claim_id != first.outbox.claim_id


@pytest.mark.asyncio
async def test_deferred_escalation_publisher_claims_and_marks_published() -> None:
    runtime, store = await _runtime()
    delegate = _RecordingEscalationPublisher()
    commits = _CommitRecorder()
    deferred = _DeferredEscalationPublisher(
        delegate=delegate,
        escalation_runtime=runtime,
        session=commits,  # type: ignore[arg-type]
        publisher_id="test:deferred",
    )

    await deferred.publish_governance_denial(
        governance_decision_id=_DENY_ID,
        tenant_id=_TENANT,
        session_id=_SESSION_ID,
    )
    await deferred.flush()

    escalation = await store.get_escalation_for_governance_decision(
        _DENY_ID,
        expected_tenant_id=_TENANT,
    )
    assert escalation is not None
    outbox = await store.get_escalation_outbox_by_escalation(
        escalation.escalation_id,
        expected_tenant_id=_TENANT,
    )
    assert outbox is not None
    assert outbox.status is EscalationOutboxStatus.PUBLISHED
    assert outbox.claim_id is not None
    assert outbox.publisher_id == "test:deferred"
    assert delegate.calls == [(_DENY_ID, _TENANT, _SESSION_ID)]
    assert commits.count == 2


@pytest.mark.asyncio
async def test_deferred_escalation_publisher_marks_failed_on_delegate_error() -> None:
    runtime, store = await _runtime()
    commits = _CommitRecorder()
    deferred = _DeferredEscalationPublisher(
        delegate=_FailingEscalationPublisher(),
        escalation_runtime=runtime,
        session=commits,  # type: ignore[arg-type]
        publisher_id="test:deferred",
    )

    await deferred.publish_governance_denial(
        governance_decision_id=_DENY_ID,
        tenant_id=_TENANT,
        session_id=_SESSION_ID,
    )
    with pytest.raises(EscalationOutboxPublishError, match="transport down"):
        await deferred.flush()

    escalation = await store.get_escalation_for_governance_decision(
        _DENY_ID,
        expected_tenant_id=_TENANT,
    )
    assert escalation is not None
    outbox = await store.get_escalation_outbox_by_escalation(
        escalation.escalation_id,
        expected_tenant_id=_TENANT,
    )
    assert outbox is not None
    assert outbox.status is EscalationOutboxStatus.FAILED
    assert outbox.claim_id is not None
    assert outbox.last_error == "RuntimeError: transport down"
    assert commits.count == 2


@pytest.mark.asyncio
async def test_deferred_escalation_publisher_rejects_unpublishable_outbox() -> None:
    runtime, _store = await _runtime()
    prepared = await runtime.prepare_governance_denial_outbox(
        governance_decision_id=_DENY_ID,
        expected_tenant_id=_TENANT,
    )
    claim = await runtime.claim_outbox_for_escalation(
        escalation_id=prepared.escalation.escalation_id,
        publisher_id="test:poison",
        expected_tenant_id=_TENANT,
    )
    assert claim.outbox is not None
    assert claim.outbox.claim_id is not None
    await runtime.mark_outbox_failed(
        outbox_id=claim.outbox.outbox_id,
        claim_id=claim.outbox.claim_id,
        error="previous terminal failure",
        expected_tenant_id=_TENANT,
    )
    deferred = _DeferredEscalationPublisher(
        delegate=_RecordingEscalationPublisher(),
        escalation_runtime=runtime,
        session=_CommitRecorder(),  # type: ignore[arg-type]
        publisher_id="test:deferred",
    )

    await deferred.publish_governance_denial(
        governance_decision_id=_DENY_ID,
        tenant_id=_TENANT,
        session_id=_SESSION_ID,
    )

    with pytest.raises(EscalationOutboxPublishError, match="failed"):
        await deferred.flush()


async def _runtime() -> tuple[EscalationAgentRuntime, InMemoryEscalationPersistence]:
    escalations = InMemoryEscalationPersistence()
    governance = InMemoryGovernanceRepository()
    sessions = InMemorySessionPersistence()
    await sessions.save_session(_session())
    await governance.record_decision(_decision())
    return (
        EscalationAgentRuntime(
            escalation_persistence=escalations,
            governance_repository=governance,
            session_persistence=sessions,
        ),
        escalations,
    )


class _RecordingEscalationPublisher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str | None]] = []

    async def publish_governance_denial(
        self,
        *,
        governance_decision_id: str,
        tenant_id: str,
        session_id: str | None = None,
    ) -> None:
        self.calls.append((governance_decision_id, tenant_id, session_id))


class _FailingEscalationPublisher:
    async def publish_governance_denial(
        self,
        *,
        governance_decision_id: str,
        tenant_id: str,
        session_id: str | None = None,
    ) -> None:
        del governance_decision_id, tenant_id, session_id
        raise RuntimeError("transport down")


class _CommitRecorder:
    def __init__(self) -> None:
        self.count = 0

    async def commit(self) -> None:
        self.count += 1


def _session() -> SessionRecord:
    sid = SessionId(uuid.UUID(_SESSION_ID))
    return SessionRecord(
        session_id=sid,
        scope=SessionScope.TENANT,
        external_handle="ticket-phase-g",
        tenant_id=_TENANT,
        principal_id="principal-agent",
        opened_at=_NOW,
        lifecycle_phase=SessionLifecyclePhase.ACTIVE,
        lifecycle_recorded_at=_NOW,
        lifecycle_reason=None,
        lineage_id=SessionLineageId(uuid.UUID(_SESSION_ID)),
        root_session_id=sid,
        parent_session_id=None,
        ancestor_session_ids=(),
        lineage_depth=0,
        sequence_head=0,
        revision=1,
    )


def _decision() -> GovernanceDecisionRecord:
    return GovernanceDecisionRecord(
        decision_id=_DENY_ID,
        decision="deny",
        stage="pre_execution",
        policy_chain_id="phase.g.test",
        reason="deny: phase-g fixture",
        decided_at=_NOW.isoformat(),
        correlation_id="corr-phase-g",
        request_id="req-phase-g",
        tenant_id=_TENANT,
        subject_kind="communication",
        metadata={"session_id": _SESSION_ID},
    )

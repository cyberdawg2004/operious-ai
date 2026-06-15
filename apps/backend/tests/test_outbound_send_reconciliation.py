"""Break-control tests for SOC2 #16a: a crash between the provider send
and ``mark_sent`` must NOT cause a duplicate customer message.

These are hermetic (in-memory persistence, real selection/transition logic
-- no mocks).
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from app.boundary.outbound.send_outbox import (
    InMemoryOutboundSendOutboxPersistence,
    OutboundSendOutboxId,
    OutboundSendOutboxRecord,
    OutboundSendOutboxRuntime,
    OutboundSendOutboxStatus,
)
from app.workers.outbound_send_tasks import (
    OutboundSendExecutionResult,
    _record_dead_letter_visibility,
    process_outbound_send_outbox_runtime,
)

_NOW = datetime(2026, 6, 15, tzinfo=timezone.utc)
_LEASE = timedelta(seconds=300)


def _record(tenant_id: str = "tenant-recon") -> OutboundSendOutboxRecord:
    return OutboundSendOutboxRecord(
        outbox_id=OutboundSendOutboxId(uuid.uuid4()),
        tenant_id=tenant_id,
        channel="email",
        action="customer_reply",
        draft_id=uuid.uuid4(),
        proposal_id=uuid.uuid4(),
        session_id=str(uuid.uuid4()),
        dispatch_id=str(uuid.uuid4()),
        governance_decision_id=uuid.uuid4(),
        recipient="customer@example.net",
        draft_body_sha256="a" * 64,
        status=OutboundSendOutboxStatus.PENDING,
        created_at=_NOW,
        updated_at=_NOW,
    )


class _Executor:
    """Stub sender with NO dedup of its own -- every call records and
    returns the next canned outcome, regardless of how many times it is
    invoked for the same outbox row."""

    def __init__(self, outcomes: list[object]) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[OutboundSendOutboxRecord] = []

    async def send(
        self,
        outbox: OutboundSendOutboxRecord,
    ) -> OutboundSendExecutionResult:
        self.calls.append(outbox)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome  # type: ignore[return-value]


class _DeadLetterSink:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    async def record(self, **kwargs: object) -> None:
        self.records.append(dict(kwargs))


class _SimulatedCrash(BaseException):
    """A hard process crash -- deliberately NOT a subclass of ``Exception``
    so ``process_outbound_send_outbox_runtime``'s ``except Exception`` does
    not catch it and run the normal reschedule path."""


class _CrashBeforeMarkSentRuntime(OutboundSendOutboxRuntime):
    """Wraps a real runtime but simulates the worker process dying after
    the provider call returns and after its evidence is recorded, but
    before ``mark_sent`` persists."""

    async def mark_sent(self, **_kwargs: Any) -> OutboundSendOutboxRecord | None:
        raise _SimulatedCrash("worker killed before mark_sent")


@pytest.mark.asyncio
async def test_b_crash_before_provider_call_requeues_and_retries_once() -> None:
    """Case 2: never reached the provider (no send_attempted_at) -> safe
    PENDING requeue -> normal retry succeeds, sender called exactly once.
    At-least-once delivery for a genuinely-interrupted send is preserved.
    """
    persistence = InMemoryOutboundSendOutboxPersistence()
    runtime = OutboundSendOutboxRuntime(persistence=persistence, retry_base_seconds=30)
    record = await persistence.create_outbound_send_outbox(_record())

    claim = await runtime.claim_due_outbox(
        outbox_id=record.outbox_id, worker_id="worker-a", claimed_at=_NOW
    )
    assert claim.claimed
    # Crash happens here -- before send_attempted_at is ever written.

    sweep = await runtime.requeue_stale_claimed(
        stale_before=_NOW + _LEASE,
        requeued_at=_NOW + _LEASE + timedelta(seconds=1),
    )
    assert sweep.requeued_count == 1
    assert sweep.sent_from_evidence == ()
    assert sweep.needs_reconciliation == ()
    requeued = sweep.requeued[0].outbox
    assert requeued is not None
    assert requeued.status is OutboundSendOutboxStatus.PENDING

    executor = _Executor([OutboundSendExecutionResult.sent("provider-1")])
    result = await process_outbound_send_outbox_runtime(
        outbox_id=str(record.outbox_id),
        outbox_runtime=runtime,
        executor=executor,
        now=_NOW + _LEASE + timedelta(seconds=2),
        worker_id="worker-b",
    )
    assert result["status"] == "sent"
    assert len(executor.calls) == 1
    final = await runtime.get_outbox(record.outbox_id)
    assert final is not None
    assert final.status is OutboundSendOutboxStatus.SENT
    assert final.provider_message_id == "provider-1"


@pytest.mark.asyncio
async def test_a2_provider_message_id_evidence_prevents_duplicate_send() -> None:
    """Case 1 (LOAD-BEARING): the provider call completed and its
    ``provider_message_id`` was recorded, but the worker crashed before
    ``mark_sent``. The reconciler must transition the stale CLAIMED row
    straight to SENT from that OUTBOX-LEVEL evidence -- never reaching the
    sender/delivery layer again.

    The stub ``_Executor`` has no dedup of its own. If the fix's
    provider_message_id evidence check were removed (reverting to a blind
    requeue-to-PENDING), this row would go back to PENDING, be reclaimed,
    and the stub sender would be called a second time -- ``executor.calls``
    would become 2 and the final assertion below would fail.
    """
    persistence = InMemoryOutboundSendOutboxPersistence()
    crashing_runtime = _CrashBeforeMarkSentRuntime(
        persistence=persistence, retry_base_seconds=30
    )
    real_runtime = OutboundSendOutboxRuntime(persistence=persistence, retry_base_seconds=30)

    record = await persistence.create_outbound_send_outbox(_record())

    executor = _Executor([OutboundSendExecutionResult.sent("provider-1")])
    with pytest.raises(_SimulatedCrash):
        await process_outbound_send_outbox_runtime(
            outbox_id=str(record.outbox_id),
            outbox_runtime=crashing_runtime,
            executor=executor,
            now=_NOW,
            worker_id="worker-a",
        )
    assert len(executor.calls) == 1

    # Crashed row: still CLAIMED, but the provider call's evidence was
    # persisted before the crash.
    crashed = await real_runtime.get_outbox(record.outbox_id)
    assert crashed is not None
    assert crashed.status is OutboundSendOutboxStatus.CLAIMED
    assert crashed.provider_message_id == "provider-1"
    assert crashed.send_attempted_at is not None

    sweep = await real_runtime.requeue_stale_claimed(
        stale_before=_NOW + _LEASE,
        requeued_at=_NOW + _LEASE + timedelta(seconds=1),
    )
    assert sweep.sent_from_evidence_count == 1
    assert sweep.requeued_count == 0
    assert sweep.needs_reconciliation_count == 0
    resolved = sweep.sent_from_evidence[0]
    assert resolved.status is OutboundSendOutboxStatus.SENT
    assert resolved.provider_message_id == "provider-1"

    # The reconciler's "enqueue due pending" pass finds nothing -- the row
    # is SENT, not PENDING, so it can never be reclaimed/resent.
    reclaim = await real_runtime.claim_due_outbox(
        outbox_id=record.outbox_id,
        worker_id="worker-b",
        claimed_at=_NOW + _LEASE + timedelta(seconds=2),
    )
    assert reclaim.claimed is False

    assert len(executor.calls) == 1


@pytest.mark.asyncio
async def test_c_ambiguous_send_outcome_needs_reconciliation_never_resent() -> None:
    """Case 3: ``send_attempted_at`` is set but ``provider_message_id`` is
    not -- the provider call may or may not have completed. Bias toward
    NOT resending: transition to NEEDS_RECONCILIATION and never
    auto-requeue, regardless of how many further reconciler sweeps run.
    """
    persistence = InMemoryOutboundSendOutboxPersistence()
    runtime = OutboundSendOutboxRuntime(persistence=persistence, retry_base_seconds=30)
    record = await persistence.create_outbound_send_outbox(_record())

    claim = await runtime.claim_due_outbox(
        outbox_id=record.outbox_id, worker_id="worker-a", claimed_at=_NOW
    )
    assert claim.claimed
    assert claim.outbox is not None
    assert claim.outbox.claim_id is not None

    # Worker reached the provider call (send_attempted_at written) but
    # crashed before the provider call returned / before
    # record_provider_message_id committed.
    attempted = await runtime.mark_send_attempted(
        outbox_id=record.outbox_id,
        claim_id=claim.outbox.claim_id,
        attempted_at=_NOW,
    )
    assert attempted is not None
    assert attempted.send_attempted_at == _NOW
    assert attempted.provider_message_id is None

    sweep = await runtime.requeue_stale_claimed(
        stale_before=_NOW + _LEASE,
        requeued_at=_NOW + _LEASE + timedelta(seconds=1),
        reason="outbound send claim expired",
    )
    assert sweep.needs_reconciliation_count == 1
    assert sweep.requeued_count == 0
    assert sweep.sent_from_evidence_count == 0
    flagged = sweep.needs_reconciliation[0]
    assert flagged.status is OutboundSendOutboxStatus.NEEDS_RECONCILIATION
    assert flagged.last_error is not None

    # Never auto-resent: the row is no longer PENDING or CLAIMED.
    reclaim = await runtime.claim_due_outbox(
        outbox_id=record.outbox_id,
        worker_id="worker-b",
        claimed_at=_NOW + _LEASE + timedelta(seconds=2),
    )
    assert reclaim.claimed is False
    assert reclaim.reason == "outbox_not_claimable:needs_reconciliation"

    # A second reconciler sweep does not touch it again -- it is no
    # longer CLAIMED.
    second_sweep = await runtime.requeue_stale_claimed(
        stale_before=_NOW + _LEASE + timedelta(seconds=10),
        requeued_at=_NOW + _LEASE + timedelta(seconds=11),
    )
    assert second_sweep.scanned == 0


@pytest.mark.asyncio
async def test_needs_reconciliation_dead_letter_visibility_is_marked_do_not_resend() -> None:
    """The operator surface for NEEDS_RECONCILIATION rows must be
    structurally distinct from a normal DEAD_LETTERED failure and
    explicitly say do-not-resend, verify-first (approved condition 1)."""
    record = replace(_record(), status=OutboundSendOutboxStatus.NEEDS_RECONCILIATION)
    sink = _DeadLetterSink()

    await _record_dead_letter_visibility(
        outbox=record,
        reason=(
            "NEEDS_RECONCILIATION: do-not-resend, verify-first -- "
            "outbound send claim went stale with an ambiguous outcome."
        ),
        session=None,
        dead_letter_sink=sink,
        created_at=_NOW,
        task_name="outbound_send_needs_reconciliation",
    )

    assert sink.records[0]["task_name"] == "outbound_send_needs_reconciliation"
    assert sink.records[0]["task_name"] != "send_outbound_draft"
    reason = sink.records[0]["reason"]
    assert isinstance(reason, str)
    assert "do-not-resend" in reason
    assert "verify-first" in reason

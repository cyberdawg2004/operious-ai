"""Admission gate and service tests for PR_T3."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Mapping

import pytest

from app.api.v1.routers.ingress import create_channel_webhook_ingress
from app.core.config import Settings
from app.db.models.admission import AdmissionRecordRow
from app.execution import celery_publisher as execution_publisher_module
from app.execution.celery_publisher import CeleryExecutionPublisher
from app.hardening.admission import (
    AdmissionChannelClass,
    AdmissionDecision,
    AdmissionGate,
    AdmissionGateThresholds,
    AdmissionOutcome,
    AdmissionReason,
)
from app.services.admission_service import AdmissionService
from app.services.ticket_ingress_service import (
    TicketIngressRejected,
    TicketIngressService,
)
from app.boundary.persistence import (
    BoundaryIngressQuery,
    InMemoryBoundaryPersistence,
)
from app.tenant.credentials import TenantCredentialEncryptor
from app.tenant.enums import TenantChannelStatus, TenantChannelType
from app.tenant.persistence import InMemoryTenantConfigurationRepository
from app.tenant.runtime import TenantConfigurationRuntime
from app.queues import DIAGNOSTIC_QUEUE_PRIORITY, QUEUE_DIAGNOSTIC_NORMAL


TENANT_ID = "tenant-admission-alpha"
WEBHOOK_SECRET = "admission-webhook-secret"


class _AdmissionRedis:
    def __init__(
        self,
        *,
        depth: int = 0,
        oldest_age_seconds: float | None = None,
        memory_info: Mapping[str, Any] | None = None,
        fail_info: bool = False,
        fail_llen: bool = False,
        fail_zrange: bool = False,
        events: list[str] | None = None,
    ) -> None:
        self.depth = depth
        self.oldest_age_seconds = oldest_age_seconds
        self.memory_info = dict(memory_info or {"used_memory": 1, "maxmemory": 0})
        self.fail_info = fail_info
        self.fail_llen = fail_llen
        self.fail_zrange = fail_zrange
        self.zadds: list[tuple[str, Mapping[str, float], bool]] = []
        self.zrems: list[tuple[str, tuple[str, ...]]] = []
        self.zremrangebyscore_calls: list[tuple[str, float | str, float | str]] = []
        self.values: dict[str, int] = {}
        self._events = events

    async def info(self, section: str | None = None) -> Mapping[str, Any]:
        del section
        if self.fail_info:
            raise RuntimeError("redis info unavailable")
        return self.memory_info

    async def llen(self, name: str) -> int:
        del name
        if self.fail_llen:
            raise RuntimeError("llen unavailable")
        return self.depth

    async def zrange(
        self,
        name: str,
        start: int,
        end: int,
        *,
        withscores: bool = False,
    ) -> list[tuple[str, float]]:
        del name, start, end, withscores
        if self.fail_zrange:
            raise RuntimeError("zrange unavailable")
        if self.oldest_age_seconds is None:
            return []
        return [("member-1", time.time() - self.oldest_age_seconds)]

    async def zadd(
        self,
        name: str,
        mapping: Mapping[str, float],
        *,
        nx: bool = False,
    ) -> int:
        if self._events is not None:
            self._events.append("zadd")
        self.zadds.append((name, mapping, nx))
        return 1

    async def zrem(self, name: str, *values: str) -> int:
        if self._events is not None:
            self._events.append("zrem")
        self.zrems.append((name, values))
        return len(values)

    async def zremrangebyscore(
        self,
        name: str,
        min_score: float | str,
        max_score: float | str,
    ) -> int:
        self.zremrangebyscore_calls.append((name, min_score, max_score))
        return 1

    async def get(self, key: str) -> int | None:
        return self.values.get(key)

    async def incr(self, key: str) -> int:
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    async def decr(self, key: str) -> int:
        self.values[key] = self.values.get(key, 0) - 1
        return self.values[key]

    async def expire(self, key: str, seconds: int) -> bool:
        del key, seconds
        return True


def _thresholds() -> AdmissionGateThresholds:
    return AdmissionGateThresholds(
        queue_depth_warn=10,
        queue_depth_reject=20,
        queue_age_warn_seconds=10,
        queue_age_reject_seconds=20,
        redis_memory_pct_warn=70,
        redis_memory_pct_reject=90,
    )


async def _decision(redis: _AdmissionRedis) -> AdmissionDecision:
    return await AdmissionGate(
        redis_client=redis,
        thresholds=_thresholds(),
    ).evaluate(queue_name=QUEUE_DIAGNOSTIC_NORMAL, tenant_id=TENANT_ID)


@pytest.mark.asyncio
async def test_admit_when_all_thresholds_below_warn() -> None:
    decision = await _decision(_AdmissionRedis(depth=1))

    assert decision.outcome is AdmissionOutcome.ADMIT
    assert decision.reason is None
    assert decision.queue_depth == 1
    assert decision.telemetry_unavailable is False


@pytest.mark.asyncio
async def test_defer_on_queue_depth_warn() -> None:
    decision = await _decision(_AdmissionRedis(depth=10))

    assert decision.outcome is AdmissionOutcome.DEFER
    assert decision.reason is AdmissionReason.QUEUE_DEPTH_EXCEEDED
    assert decision.retry_after_seconds == 15


@pytest.mark.asyncio
async def test_reject_on_queue_depth_reject() -> None:
    decision = await _decision(_AdmissionRedis(depth=20))

    assert decision.outcome is AdmissionOutcome.REJECT
    assert decision.reason is AdmissionReason.QUEUE_DEPTH_EXCEEDED
    assert decision.retry_after_seconds == 30


@pytest.mark.asyncio
async def test_defer_on_queue_age_warn() -> None:
    """A genuine backlog (real depth, real age) must still warn-defer."""
    decision = await _decision(_AdmissionRedis(depth=1, oldest_age_seconds=10.5))

    assert decision.outcome is AdmissionOutcome.DEFER
    assert decision.reason is AdmissionReason.QUEUE_AGE_EXCEEDED


@pytest.mark.asyncio
async def test_reject_on_queue_age_reject() -> None:
    """A genuine backlog (real depth, real age) must still hard-reject."""
    decision = await _decision(_AdmissionRedis(depth=1, oldest_age_seconds=21))

    assert decision.outcome is AdmissionOutcome.REJECT
    assert decision.reason is AdmissionReason.QUEUE_AGE_EXCEEDED


@pytest.mark.asyncio
async def test_orphaned_age_sentinel_with_zero_depth_does_not_false_reject() -> None:
    """LOAD-BEARING: an orphaned ``queue:age:{queue}`` member left by a
    publish/dequeue race must never claim a multi-hour backlog when the
    broker's actual depth for that queue is 0. Reproduces the live
    false-reject incident (2.6h sentinel age, depth 0, every dispatch
    rejected with QUEUE_AGE_EXCEEDED).
    """
    redis = _AdmissionRedis(depth=0, oldest_age_seconds=9_360)

    decision = await _decision(redis)

    assert decision.outcome is AdmissionOutcome.ADMIT
    assert decision.reason is not AdmissionReason.QUEUE_AGE_EXCEEDED
    assert decision.queue_age_available is True


@pytest.mark.asyncio
async def test_orphaned_age_sentinel_is_reconciled_when_client_supports_cleanup() -> None:
    """The depth-zero override also clears the stale member when the
    redis client exposes ``zremrangebyscore``, so the same orphan can't
    keep costing a reconciliation check on every future evaluation.
    """
    redis = _AdmissionRedis(depth=0, oldest_age_seconds=9_360)

    await _decision(redis)

    assert redis.zremrangebyscore_calls
    key, min_score, max_score = redis.zremrangebyscore_calls[0]
    assert key == f"queue:age:{QUEUE_DIAGNOSTIC_NORMAL}"
    assert min_score == "-inf"
    assert isinstance(max_score, float)


@pytest.mark.asyncio
async def test_unavailable_depth_does_not_suppress_real_age_signal() -> None:
    """If depth telemetry itself is unavailable, the gate must not assume
    depth is zero -- the existing sentinel score must still be trusted so
    a genuine backlog isn't masked by an unrelated telemetry outage.
    """
    redis = _AdmissionRedis(fail_llen=True, oldest_age_seconds=21)

    decision = await _decision(redis)

    assert decision.outcome is AdmissionOutcome.REJECT
    assert decision.reason is AdmissionReason.QUEUE_AGE_EXCEEDED


@pytest.mark.asyncio
async def test_reject_on_redis_memory_pressure_reject() -> None:
    decision = await _decision(
        _AdmissionRedis(memory_info={"used_memory": 95, "maxmemory": 100})
    )

    assert decision.outcome is AdmissionOutcome.REJECT
    assert decision.reason is AdmissionReason.REDIS_MEMORY_PRESSURE


@pytest.mark.asyncio
async def test_admission_decision_id_is_deterministic_for_request_scope() -> None:
    gate = AdmissionGate(
        redis_client=_AdmissionRedis(depth=20),
        thresholds=_thresholds(),
    )

    first = await gate.evaluate(
        queue_names=DIAGNOSTIC_QUEUE_PRIORITY,
        tenant_id=TENANT_ID,
        channel="email",
        request_correlation_id="request-admission-1",
    )
    second = await gate.evaluate(
        queue_names=DIAGNOSTIC_QUEUE_PRIORITY,
        tenant_id=TENANT_ID,
        channel="email",
        request_correlation_id="request-admission-1",
    )

    assert first.decision_id == second.decision_id


@pytest.mark.asyncio
async def test_defer_on_db_pool_wait_warn() -> None:
    decision = await AdmissionGate(
        redis_client=_AdmissionRedis(depth=0),
        thresholds=_thresholds(),
    ).evaluate(
        queue_name=QUEUE_DIAGNOSTIC_NORMAL,
        tenant_id=TENANT_ID,
        db_pool_wait_ms=250,
    )

    assert decision.outcome is AdmissionOutcome.DEFER
    assert decision.reason is AdmissionReason.DB_POOL_PRESSURE


@pytest.mark.asyncio
async def test_reject_on_db_pool_wait_reject() -> None:
    decision = await AdmissionGate(
        redis_client=_AdmissionRedis(depth=0),
        thresholds=_thresholds(),
    ).evaluate(
        queue_name=QUEUE_DIAGNOSTIC_NORMAL,
        tenant_id=TENANT_ID,
        db_pool_wait_ms=1000,
    )

    assert decision.outcome is AdmissionOutcome.REJECT
    assert decision.reason is AdmissionReason.DB_POOL_PRESSURE


@pytest.mark.asyncio
async def test_redis_memory_unavailable_admits_when_otherwise_healthy() -> None:
    """LOAD-BEARING: a Redis telemetry probe outage must not dead-letter
    otherwise-healthy traffic. Telemetry is a monitoring signal, not
    backpressure -- ``telemetry_unavailable`` stays true for observability,
    but the decision must ADMIT so an idle queue doesn't drop customer mail.
    """
    decision = await _decision(_AdmissionRedis(fail_info=True))

    assert decision.outcome is AdmissionOutcome.ADMIT
    assert decision.reason is AdmissionReason.TELEMETRY_UNAVAILABLE_PROCESSING
    assert decision.redis_memory_pct is None
    assert decision.redis_memory_available is False
    assert decision.telemetry_unavailable is True
    assert decision.unavailable_reasons == ("redis_memory_unavailable",)


@pytest.mark.asyncio
async def test_queue_age_unavailable_admits_when_otherwise_healthy() -> None:
    decision = await _decision(_AdmissionRedis(fail_zrange=True))

    assert decision.outcome is AdmissionOutcome.ADMIT
    assert decision.reason is AdmissionReason.TELEMETRY_UNAVAILABLE_PROCESSING
    assert decision.queue_age_seconds is None
    assert decision.queue_age_available is False
    assert decision.telemetry_unavailable is True
    assert decision.unavailable_reasons == (
        f"queue_age_unavailable:{QUEUE_DIAGNOSTIC_NORMAL}",
    )


@pytest.mark.asyncio
async def test_queue_depth_unavailable_admits_with_depth_zero() -> None:
    decision = await _decision(_AdmissionRedis(fail_llen=True))

    assert decision.outcome is AdmissionOutcome.ADMIT
    assert decision.reason is AdmissionReason.TELEMETRY_UNAVAILABLE_PROCESSING
    assert decision.queue_depth == 0
    assert decision.queue_depth_available is False
    assert decision.telemetry_unavailable is True
    assert decision.unavailable_reasons == (
        f"queue_depth_unavailable:{QUEUE_DIAGNOSTIC_NORMAL}",
    )


@pytest.mark.asyncio
async def test_telemetry_unavailable_with_real_db_pool_pressure_still_defers() -> None:
    """AD-2: telemetry being unavailable must not mask genuine backpressure.
    A high db_pool_wait_ms (a real, directly-measured signal, independent of
    the Redis telemetry probe) must still DEFER even when Redis telemetry is
    also down.
    """
    decision = await AdmissionGate(
        redis_client=_AdmissionRedis(fail_info=True),
        thresholds=_thresholds(),
    ).evaluate(
        queue_name=QUEUE_DIAGNOSTIC_NORMAL,
        tenant_id=TENANT_ID,
        db_pool_wait_ms=300,
    )

    assert decision.outcome is AdmissionOutcome.DEFER
    assert decision.reason is AdmissionReason.DB_POOL_PRESSURE
    assert decision.telemetry_unavailable is True


@pytest.mark.asyncio
async def test_telemetry_unavailable_with_real_queue_depth_pressure_still_defers() -> None:
    """AD-2: a real high queue depth (measured successfully) must still DEFER
    even when other telemetry (queue age) is unavailable.
    """
    decision = await AdmissionGate(
        redis_client=_AdmissionRedis(depth=10, fail_zrange=True),
        thresholds=_thresholds(),
    ).evaluate(queue_name=QUEUE_DIAGNOSTIC_NORMAL, tenant_id=TENANT_ID)

    assert decision.outcome is AdmissionOutcome.DEFER
    assert decision.reason is AdmissionReason.QUEUE_DEPTH_EXCEEDED
    assert decision.telemetry_unavailable is True


@pytest.mark.asyncio
async def test_realtime_chat_defers_when_telemetry_unavailable() -> None:
    decision = await AdmissionGate(
        redis_client=_AdmissionRedis(fail_llen=True),
        thresholds=_thresholds(),
    ).evaluate(
        queue_name=QUEUE_DIAGNOSTIC_NORMAL,
        tenant_id=TENANT_ID,
        channel="webchat",
    )

    assert decision.outcome is AdmissionOutcome.DEFER
    assert decision.reason is AdmissionReason.TELEMETRY_UNAVAILABLE_REALTIME
    assert decision.channel_class is AdmissionChannelClass.REALTIME_CHAT


@pytest.mark.asyncio
async def test_voice_rejects_when_telemetry_unavailable() -> None:
    decision = await AdmissionGate(
        redis_client=_AdmissionRedis(fail_llen=True),
        thresholds=_thresholds(),
    ).evaluate(
        queue_name=QUEUE_DIAGNOSTIC_NORMAL,
        tenant_id=TENANT_ID,
        channel="voice",
    )

    assert decision.outcome is AdmissionOutcome.REJECT
    assert decision.reason is AdmissionReason.TELEMETRY_UNAVAILABLE_VOICE
    assert decision.channel_class is AdmissionChannelClass.VOICE


@pytest.mark.asyncio
async def test_non_admit_decision_is_persisted() -> None:
    session_factory = _RecordingSessionFactory()
    service = AdmissionService(
        gate=AdmissionGate(
            redis_client=_AdmissionRedis(depth=20),
            thresholds=_thresholds(),
        ),
        session_factory=session_factory,  # type: ignore[arg-type]
    )

    decision = await service.evaluate_and_persist(
        queue_name=QUEUE_DIAGNOSTIC_NORMAL,
        tenant_id=TENANT_ID,
        channel="email",
    )

    row = session_factory.rows[0]
    assert row is not None
    assert row.decision_id == decision.decision_id
    assert row.outcome == AdmissionOutcome.REJECT.value
    assert row.reason == AdmissionReason.QUEUE_DEPTH_EXCEEDED.value
    assert row.db_pool_wait_ms is None
    assert session_factory.commits == 1


@pytest.mark.asyncio
async def test_admit_decision_is_not_persisted() -> None:
    session_factory = _RecordingSessionFactory()
    service = AdmissionService(
        gate=AdmissionGate(
            redis_client=_AdmissionRedis(depth=0),
            thresholds=_thresholds(),
        ),
        session_factory=session_factory,  # type: ignore[arg-type]
    )

    decision = await service.evaluate_and_persist(
        queue_name=QUEUE_DIAGNOSTIC_NORMAL,
        tenant_id=TENANT_ID,
        channel="email",
    )

    assert decision.outcome is AdmissionOutcome.ADMIT
    assert session_factory.rows == []
    assert session_factory.commits == 0


@pytest.mark.asyncio
async def test_persistence_failure_is_non_fatal() -> None:
    service = AdmissionService(
        gate=AdmissionGate(
            redis_client=_AdmissionRedis(depth=20),
            thresholds=_thresholds(),
        ),
        session_factory=_BrokenSessionFactory(),  # type: ignore[arg-type]
    )

    decision = await service.evaluate_and_persist(
        queue_name=QUEUE_DIAGNOSTIC_NORMAL,
        tenant_id=TENANT_ID,
        channel="email",
    )

    assert decision.outcome is AdmissionOutcome.REJECT


def test_admission_record_decision_id_is_primary_key() -> None:
    primary_keys = {
        column.name
        for column in AdmissionRecordRow.__table__.primary_key.columns
    }

    assert primary_keys == {"decision_id"}


@pytest.mark.asyncio
async def test_execution_publisher_writes_queue_age_sentinel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _AdmissionRedis(depth=0)
    task = _FakeTask()
    monkeypatch.setattr(
        execution_publisher_module,
        "_running_under_pytest",
        lambda: False,
    )
    monkeypatch.setattr(
        execution_publisher_module,
        "execute_diagnostic_agent",
        task,
    )
    publisher = CeleryExecutionPublisher(
        redis_client=redis,  # type: ignore[arg-type]
        queue_name=QUEUE_DIAGNOSTIC_NORMAL,
        max_queue_depth=100,
        run_inline_under_pytest=False,
    )

    await publisher.publish_execution("execution-admission", tenant_id=TENANT_ID)

    assert task.calls[0]["queue"] == QUEUE_DIAGNOSTIC_NORMAL
    assert redis.zadds
    key, mapping, nx = redis.zadds[0]
    assert key == f"queue:age:{QUEUE_DIAGNOSTIC_NORMAL}"
    assert set(mapping) == {"execution-admission"}
    assert nx is True


@pytest.mark.asyncio
async def test_execution_publisher_writes_sentinel_before_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LOAD-BEARING: the sentinel must be visible before the task is
    dispatchable. If a worker could dequeue and clear it first, the
    publisher's later write would orphan the member permanently --
    the exact mechanism behind the live false-reject incident.
    """
    events: list[str] = []
    redis = _AdmissionRedis(depth=0, events=events)
    task = _FakeTask(events=events)
    monkeypatch.setattr(
        execution_publisher_module,
        "_running_under_pytest",
        lambda: False,
    )
    monkeypatch.setattr(
        execution_publisher_module,
        "execute_diagnostic_agent",
        task,
    )
    publisher = CeleryExecutionPublisher(
        redis_client=redis,  # type: ignore[arg-type]
        queue_name=QUEUE_DIAGNOSTIC_NORMAL,
        max_queue_depth=100,
        run_inline_under_pytest=False,
    )

    await publisher.publish_execution("execution-order", tenant_id=TENANT_ID)

    assert events == ["zadd", "apply_async"]


@pytest.mark.asyncio
async def test_execution_publisher_clears_sentinel_when_dispatch_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the broker rejects the publish after the sentinel was written,
    the publisher must compensate by clearing it -- otherwise the task
    never runs (so the worker-side clear never fires either) and the
    sentinel is orphaned forever.
    """
    redis = _AdmissionRedis(depth=0)
    task = _FakeTask(raise_on_apply_async=RuntimeError("broker unavailable"))
    monkeypatch.setattr(
        execution_publisher_module,
        "_running_under_pytest",
        lambda: False,
    )
    monkeypatch.setattr(
        execution_publisher_module,
        "execute_diagnostic_agent",
        task,
    )
    publisher = CeleryExecutionPublisher(
        redis_client=redis,  # type: ignore[arg-type]
        queue_name=QUEUE_DIAGNOSTIC_NORMAL,
        max_queue_depth=100,
        run_inline_under_pytest=False,
    )

    with pytest.raises(RuntimeError, match="broker unavailable"):
        await publisher.publish_execution("execution-failed-dispatch", tenant_id=TENANT_ID)

    assert redis.zadds
    assert redis.zrems
    key, members = redis.zrems[0]
    assert key == f"queue:age:{QUEUE_DIAGNOSTIC_NORMAL}"
    assert members == ("execution-failed-dispatch",)


@pytest.mark.asyncio
async def test_webhook_reject_decision_preserves_captured_ingress() -> None:
    boundary_store = InMemoryBoundaryPersistence()
    service = await _webhook_service(
        boundary_store=boundary_store,
        admission_service=_FakeAdmissionService(AdmissionOutcome.REJECT),
    )
    body = _email_body(nonce="reject-1")
    raw_body = _raw(body)

    result = await service.process_channel_webhook(
        channel_type="email",
        body=body,
        headers=_signed_headers(raw_body),
        raw_body=raw_body,
        content_type="application/json",
    )

    assert result.ingress_id
    page = await boundary_store.list_ingress(
        BoundaryIngressQuery(),
        expected_tenant_id=TENANT_ID,
    )
    assert page.total == 1


@pytest.mark.asyncio
async def test_webhook_defer_decision_preserves_captured_ingress() -> None:
    boundary_store = InMemoryBoundaryPersistence()
    service = await _webhook_service(
        boundary_store=boundary_store,
        admission_service=_FakeAdmissionService(AdmissionOutcome.DEFER),
    )
    body = _email_body(nonce="defer-1")
    raw_body = _raw(body)

    result = await service.process_channel_webhook(
        channel_type="email",
        body=body,
        headers=_signed_headers(raw_body),
        raw_body=raw_body,
        content_type="application/json",
    )

    assert result.ingress_id
    page = await boundary_store.list_ingress(
        BoundaryIngressQuery(),
        expected_tenant_id=TENANT_ID,
    )
    assert page.total == 1


@pytest.mark.asyncio
async def test_webhook_redis_unavailable_preserves_captured_ingress() -> None:
    boundary_store = InMemoryBoundaryPersistence()
    session_factory = _RecordingSessionFactory()
    admission_service = AdmissionService(
        gate=AdmissionGate(
            redis_client=_AdmissionRedis(fail_llen=True),
            thresholds=_thresholds(),
        ),
        session_factory=session_factory,  # type: ignore[arg-type]
    )
    service = await _webhook_service(
        boundary_store=boundary_store,
        admission_service=admission_service,
    )
    body = _email_body(nonce="redis-down-1")
    raw_body = _raw(body)

    result = await service.process_channel_webhook(
        channel_type="email",
        body=body,
        headers=_signed_headers(raw_body),
        raw_body=raw_body,
        content_type="application/json",
    )

    assert result.ingress_id
    page = await boundary_store.list_ingress(
        BoundaryIngressQuery(),
        expected_tenant_id=TENANT_ID,
    )
    assert page.total == 1
    # Redis telemetry is down but the admission decision still ADMITs (an
    # otherwise-healthy queue must not be deferred to death). The admission
    # record is still persisted for observability, with outcome=ADMIT and
    # reason=telemetry_unavailable_processing.
    assert session_factory.commits == 1
    assert session_factory.rows[0].outcome == AdmissionOutcome.ADMIT.value
    assert (
        session_factory.rows[0].reason
        == AdmissionReason.TELEMETRY_UNAVAILABLE_PROCESSING.value
    )


@pytest.mark.asyncio
async def test_admit_webhook_does_not_return_429_or_503() -> None:
    boundary_store = InMemoryBoundaryPersistence()
    service = await _webhook_service(
        boundary_store=boundary_store,
        admission_service=_FakeAdmissionService(AdmissionOutcome.ADMIT),
    )
    body = _email_body(nonce="admit-1")
    raw_body = _raw(body)

    result = await service.process_channel_webhook(
        channel_type="email",
        body=body,
        headers=_signed_headers(raw_body),
        raw_body=raw_body,
        content_type="application/json",
    )

    assert result.ingress_id
    page = await boundary_store.list_ingress(
        BoundaryIngressQuery(),
        expected_tenant_id=TENANT_ID,
    )
    assert page.total == 1


@pytest.mark.asyncio
async def test_signature_validation_happens_before_admission() -> None:
    admission_service = _FakeAdmissionService(AdmissionOutcome.REJECT)
    service = await _webhook_service(admission_service=admission_service)
    body = _email_body(nonce="invalid-signature")

    with pytest.raises(TicketIngressRejected) as exc_info:
        await service.process_channel_webhook(
            channel_type="email",
            body=body,
            headers={"X-Operious-Signature": "sha256=bad"},
            raw_body=_raw(body),
            content_type="application/json",
        )

    assert exc_info.value.status_code == 401
    assert exc_info.value.code == "webhook_rejected"
    assert admission_service.calls == []


@pytest.mark.asyncio
async def test_duplicate_webhook_ack_precedes_admission_pressure() -> None:
    boundary_store = InMemoryBoundaryPersistence()
    service = await _webhook_service(
        boundary_store=boundary_store,
        admission_service=_MutableAdmissionService(),
    )
    body = _email_body(nonce="duplicate-under-pressure")
    raw_body = _raw(body)
    headers = _signed_headers(raw_body)

    first = await service.process_channel_webhook(
        channel_type="email",
        body=body,
        headers=headers,
        raw_body=raw_body,
        content_type="application/json",
    )
    service._admission_service = _FakeAdmissionService(AdmissionOutcome.REJECT)
    second = await service.process_channel_webhook(
        channel_type="email",
        body=body,
        headers=headers,
        raw_body=raw_body,
        content_type="application/json",
    )

    assert first.ingress_id
    assert second.status == "duplicate_delivery_acknowledged"


@pytest.mark.asyncio
async def test_router_returns_admission_response_body() -> None:
    decision_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "router-admission"))
    service = _RouterAdmissionRejectService(decision_id=decision_id)

    response = await create_channel_webhook_ingress(
        channel_type="email",
        request=_FakeRequest(
            body=b'{"message_id":"email-1","to":"support@example.com"}',
            headers={"content-type": "application/json"},
        ),  # type: ignore[arg-type]
        expected_tenant_id=None,
        service=service,  # type: ignore[arg-type]
    )

    assert response.status_code == 429
    assert response.headers["x-operious-admission-decision-id"] == decision_id
    assert json.loads(response.body)["error"] == "admission_rejected"


def test_admission_settings_are_env_overridable() -> None:
    settings = Settings(
        ADMISSION_QUEUE_DEPTH_WARN=11,
        ADMISSION_QUEUE_DEPTH_REJECT=22,
        ADMISSION_QUEUE_AGE_WARN_SECONDS=33,
        ADMISSION_QUEUE_AGE_REJECT_SECONDS=44,
        ADMISSION_REDIS_MEMORY_PCT_WARN=55.5,
        ADMISSION_REDIS_MEMORY_PCT_REJECT=66.5,
        ADMISSION_DB_POOL_WAIT_WARN_MS=77.5,
        ADMISSION_DB_POOL_WAIT_REJECT_MS=88.5,
    )

    assert settings.ADMISSION_QUEUE_DEPTH_WARN == 11
    assert settings.ADMISSION_QUEUE_DEPTH_REJECT == 22
    assert settings.ADMISSION_QUEUE_AGE_WARN_SECONDS == 33
    assert settings.ADMISSION_QUEUE_AGE_REJECT_SECONDS == 44
    assert settings.ADMISSION_REDIS_MEMORY_PCT_WARN == 55.5
    assert settings.ADMISSION_REDIS_MEMORY_PCT_REJECT == 66.5
    assert settings.ADMISSION_DB_POOL_WAIT_WARN_MS == 77.5
    assert settings.ADMISSION_DB_POOL_WAIT_REJECT_MS == 88.5


class _BrokenSession:
    async def __aenter__(self) -> "_BrokenSession":
        return self

    async def __aexit__(
        self,
        exc_type: object,
        exc: object,
        traceback: object,
    ) -> None:
        del exc_type, exc, traceback

    def add(self, value: object) -> None:
        del value

    async def commit(self) -> None:
        raise RuntimeError("commit failed")


class _BrokenSessionFactory:
    def __call__(self) -> _BrokenSession:
        return _BrokenSession()


class _RecordingSession:
    def __init__(self, factory: "_RecordingSessionFactory") -> None:
        self._factory = factory

    async def __aenter__(self) -> "_RecordingSession":
        return self

    async def __aexit__(
        self,
        exc_type: object,
        exc: object,
        traceback: object,
    ) -> None:
        del exc_type, exc, traceback

    def add(self, value: object) -> None:
        assert isinstance(value, AdmissionRecordRow)
        self._factory.rows.append(value)

    async def commit(self) -> None:
        self._factory.commits += 1


class _RecordingSessionFactory:
    def __init__(self) -> None:
        self.rows: list[AdmissionRecordRow] = []
        self.commits = 0

    def __call__(self) -> _RecordingSession:
        return _RecordingSession(self)


class _FakeTask:
    def __init__(
        self,
        *,
        events: list[str] | None = None,
        raise_on_apply_async: Exception | None = None,
    ) -> None:
        self.calls: list[dict[str, object]] = []
        self._events = events
        self._raise_on_apply_async = raise_on_apply_async

    def apply_async(self, **kwargs: object) -> None:
        if self._events is not None:
            self._events.append("apply_async")
        if self._raise_on_apply_async is not None:
            raise self._raise_on_apply_async
        self.calls.append(kwargs)


class _FakeSession:
    async def rollback(self) -> None:
        return None

    async def commit(self) -> None:
        return None


class _FakeAdmissionService:
    def __init__(self, outcome: AdmissionOutcome) -> None:
        self.outcome = outcome
        self.calls: list[dict[str, object]] = []

    async def evaluate_and_persist(
        self,
        *,
        queue_name: str | None = None,
        queue_names: tuple[str, ...] | None = None,
        tenant_id: str | None = None,
        channel: str | None = None,
        request_correlation_id: str | None = None,
    ) -> AdmissionDecision:
        queue_identity = ",".join(queue_names or ((queue_name,) if queue_name else ()))
        self.calls.append(
            {
                "queue_name": queue_identity,
                "queue_names": queue_names,
                "tenant_id": tenant_id,
                "channel": channel,
                "request_correlation_id": request_correlation_id,
            }
        )
        return _admission_decision(
            outcome=self.outcome,
            queue_name=queue_identity,
        )


class _MutableAdmissionService(_FakeAdmissionService):
    def __init__(self) -> None:
        super().__init__(AdmissionOutcome.ADMIT)


class _RouterAdmissionRejectService:
    def __init__(self, *, decision_id: str) -> None:
        self.decision_id = decision_id

    async def process_channel_webhook(self, **kwargs: object) -> object:
        del kwargs
        raise TicketIngressRejected(
            code="admission_rejected",
            reason=AdmissionReason.QUEUE_DEPTH_EXCEEDED.value,
            status_code=429,
            headers={"X-Operious-Admission-Decision-Id": self.decision_id},
            response_body={
                "error": "admission_rejected",
                "reason": AdmissionReason.QUEUE_DEPTH_EXCEEDED.value,
                "decision_id": self.decision_id,
                "message": "Platform capacity exceeded. Request rejected.",
            },
        )


class _FakeRequest:
    def __init__(
        self,
        *,
        body: bytes,
        headers: dict[str, str],
        path: str = "/api/v1/ingress/channels/email/webhook",
    ) -> None:
        self.headers = headers
        self._body = body
        self.url = SimpleNamespace(path=path)

    async def body(self) -> bytes:
        return self._body


async def _webhook_service(
    *,
    boundary_store: InMemoryBoundaryPersistence | None = None,
    admission_service: object | None = None,
) -> TicketIngressService:
    tenant_runtime = TenantConfigurationRuntime(
        repository=InMemoryTenantConfigurationRepository(),
        credential_encryptor=TenantCredentialEncryptor(
            platform_master_key="admission-master-key-32-bytes-min",
        ),
    )
    await tenant_runtime.configure_channel(
        tenant_id=TENANT_ID,
        channel_type=TenantChannelType.EMAIL,
        routing_address="support@example.com",
        credentials={"token": "email-token"},
        webhook_secret=WEBHOOK_SECRET,
        status=TenantChannelStatus.ACTIVE,
    )
    return TicketIngressService(
        persistence=boundary_store or InMemoryBoundaryPersistence(),
        session=_FakeSession(),  # type: ignore[arg-type]
        tenant_configuration_runtime=tenant_runtime,
        admission_service=admission_service,  # type: ignore[arg-type]
        webhook_queue_by_channel={
            TenantChannelType.EMAIL: DIAGNOSTIC_QUEUE_PRIORITY,
        },
    )


def _admission_decision(
    *,
    outcome: AdmissionOutcome,
    queue_name: str,
) -> AdmissionDecision:
    reason = (
        None
        if outcome is AdmissionOutcome.ADMIT
        else AdmissionReason.QUEUE_DEPTH_EXCEEDED
    )
    return AdmissionDecision(
        decision_id=uuid.uuid5(uuid.NAMESPACE_URL, f"admission-test:{outcome}"),
        outcome=outcome,
        reason=reason,
        queue_name=queue_name,
        queue_depth=20,
        queue_age_seconds=None,
        redis_memory_pct=None,
        db_pool_wait_ms=None,
        retry_after_seconds=15,
        evaluated_at=datetime.now(timezone.utc),
    )


def _email_body(*, nonce: str) -> dict[str, object]:
    return {
        "message_id": nonce,
        "nonce": nonce,
        "to": "support@example.com",
        "text": "hello",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _signed_headers(raw_body: bytes) -> dict[str, str]:
    digest = hmac.new(
        WEBHOOK_SECRET.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return {"X-Operious-Signature": f"sha256={digest}"}


def _raw(body: object) -> bytes:
    return json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

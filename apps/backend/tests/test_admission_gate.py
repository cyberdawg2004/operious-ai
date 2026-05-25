"""Admission gate and service tests for PR_T3."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

import pytest

from app.api.v1.routers.ingress import create_channel_webhook_ingress
from app.core.config import Settings
from app.db.models.admission import AdmissionRecordRow
from app.execution import celery_publisher as execution_publisher_module
from app.execution.celery_publisher import CeleryExecutionPublisher
from app.hardening.admission import (
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
        fail_zrange: bool = False,
    ) -> None:
        self.depth = depth
        self.oldest_age_seconds = oldest_age_seconds
        self.memory_info = dict(memory_info or {"used_memory": 1, "maxmemory": 0})
        self.fail_info = fail_info
        self.fail_zrange = fail_zrange
        self.zadds: list[tuple[str, Mapping[str, float], bool]] = []

    async def info(self, section: str | None = None) -> Mapping[str, Any]:
        del section
        if self.fail_info:
            raise RuntimeError("redis info unavailable")
        return self.memory_info

    async def llen(self, name: str) -> int:
        del name
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
        self.zadds.append((name, mapping, nx))
        return 1


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
    decision = await _decision(_AdmissionRedis(oldest_age_seconds=10.5))

    assert decision.outcome is AdmissionOutcome.DEFER
    assert decision.reason is AdmissionReason.QUEUE_AGE_EXCEEDED


@pytest.mark.asyncio
async def test_reject_on_queue_age_reject() -> None:
    decision = await _decision(_AdmissionRedis(oldest_age_seconds=21))

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
async def test_redis_memory_unavailable_fails_open() -> None:
    decision = await _decision(_AdmissionRedis(fail_info=True))

    assert decision.outcome is AdmissionOutcome.ADMIT
    assert decision.redis_memory_pct is None


@pytest.mark.asyncio
async def test_queue_age_unavailable_fails_open() -> None:
    decision = await _decision(_AdmissionRedis(fail_zrange=True))

    assert decision.outcome is AdmissionOutcome.ADMIT
    assert decision.queue_age_seconds is None


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
async def test_webhook_reject_returns_429_and_headers() -> None:
    service = await _webhook_service(
        admission_service=_FakeAdmissionService(AdmissionOutcome.REJECT),
    )
    body = _email_body(nonce="reject-1")
    raw_body = _raw(body)

    with pytest.raises(TicketIngressRejected) as exc_info:
        await service.process_channel_webhook(
            channel_type="email",
            body=body,
            headers=_signed_headers(raw_body),
            raw_body=raw_body,
            content_type="application/json",
        )

    assert exc_info.value.status_code == 429
    assert exc_info.value.headers["X-Operious-Admission-Decision-Id"]
    assert exc_info.value.response_body is not None
    assert exc_info.value.response_body["error"] == "admission_rejected"


@pytest.mark.asyncio
async def test_webhook_defer_returns_503_retry_after_and_headers() -> None:
    service = await _webhook_service(
        admission_service=_FakeAdmissionService(AdmissionOutcome.DEFER),
    )
    body = _email_body(nonce="defer-1")
    raw_body = _raw(body)

    with pytest.raises(TicketIngressRejected) as exc_info:
        await service.process_channel_webhook(
            channel_type="email",
            body=body,
            headers=_signed_headers(raw_body),
            raw_body=raw_body,
            content_type="application/json",
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.headers["Retry-After"] == "15"
    assert exc_info.value.response_body is not None
    assert exc_info.value.response_body["error"] == "admission_deferred"


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
    assert exc_info.value.code == "invalid_signature"
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
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def apply_async(self, **kwargs: object) -> None:
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
    ) -> None:
        self.headers = headers
        self._body = body

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

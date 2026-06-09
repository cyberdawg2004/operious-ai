from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

import pytest

from app.api.v1.schemas.health import HealthResponse
from app.api.v1.schemas.queue_operations import QueueStatusResponse
from app.core.config import Settings, get_settings
from app.core.queue_depth import (
    QueueDepthSample,
    QueueDepthUnavailable,
    RabbitMQQueueDepthProvider,
    RedisQueueDepthProvider,
)
from app.hardening.admission import (
    AdmissionGate,
    AdmissionGateThresholds,
    AdmissionOutcome,
    AdmissionReason,
)
from app.queues import QUEUE_DIAGNOSTIC_NORMAL
from app.services.health_service import HealthService
from app.services.queue_operations_service import QueueOperationsService


class _RedisDepth:
    def __init__(self, *, depth: int) -> None:
        self.depth = depth
        self.calls: list[str] = []

    async def llen(self, name: str) -> int:
        self.calls.append(name)
        return self.depth


class _RabbitHTTPResponse:
    def __init__(
        self,
        *,
        payload: Mapping[str, object] | None = None,
        status_code: int = 200,
    ) -> None:
        self._payload = dict(
            payload
            or {
                "messages_ready": 4,
                "messages_unacknowledged": 2,
                "messages": 6,
            }
        )
        self.status_code = status_code
        self.text = "rabbitmq response"

    def json(self) -> dict[str, object]:
        return dict(self._payload)


class _RabbitHTTPClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, str], float]] = []
        self.fail = False
        self.payload: Mapping[str, object] = {
            "messages_ready": 4,
            "messages_unacknowledged": 2,
            "messages": 6,
        }

    async def get(
        self,
        url: str,
        *,
        auth: tuple[str, str],
        timeout: float,
    ) -> _RabbitHTTPResponse:
        self.calls.append((url, auth, timeout))
        if self.fail:
            raise RuntimeError("rabbitmq unavailable")
        return _RabbitHTTPResponse(payload=self.payload)


class _AdmissionRedis:
    async def info(self, section: str | None = None) -> Mapping[str, Any]:
        del section
        return {"used_memory": 1, "maxmemory": 0}

    async def zrange(
        self,
        name: str,
        start: int,
        end: int,
        *,
        withscores: bool = False,
    ) -> list[tuple[str, float]]:
        del name, start, end, withscores
        return []


class _StaticDepthProvider:
    backend = "rabbitmq"

    def __init__(
        self,
        samples: Mapping[str, QueueDepthSample] | None = None,
        *,
        default_depth: int = 0,
    ) -> None:
        self.samples = dict(samples or {})
        self.default_depth = default_depth
        self.calls: list[str] = []

    async def get_queue_depth(self, queue_name: str) -> QueueDepthSample:
        self.calls.append(queue_name)
        return self.samples.get(
            queue_name,
            QueueDepthSample(queue_name=queue_name, depth=self.default_depth),
        )


@pytest.mark.asyncio
async def test_redis_queue_depth_provider_uses_llen() -> None:
    redis = _RedisDepth(depth=9)
    sample = await RedisQueueDepthProvider(redis).get_queue_depth(
        QUEUE_DIAGNOSTIC_NORMAL
    )

    assert sample.depth == 9
    assert redis.calls == [QUEUE_DIAGNOSTIC_NORMAL]


@pytest.mark.asyncio
async def test_rabbitmq_provider_encodes_default_vhost_and_exposes_counts() -> None:
    client = _RabbitHTTPClient()
    provider = RabbitMQQueueDepthProvider(
        settings=_rabbit_settings(),
        http_client=client,
    )

    sample = await provider.get_queue_depth(QUEUE_DIAGNOSTIC_NORMAL)

    assert client.calls[0][0] == (
        "https://rabbit.example/api/queues/%2F/diagnostic.normal"
    )
    assert sample.depth == 4
    assert sample.messages_ready == 4
    assert sample.messages_unacknowledged == 2
    assert sample.messages == 6


@pytest.mark.asyncio
async def test_rabbitmq_provider_caches_within_ttl() -> None:
    client = _RabbitHTTPClient()
    now = 100.0
    provider = RabbitMQQueueDepthProvider(
        settings=_rabbit_settings(ttl_seconds=10),
        http_client=client,
        monotonic=lambda: now,
    )

    first = await provider.get_queue_depth(QUEUE_DIAGNOSTIC_NORMAL)
    client.payload = {
        "messages_ready": 99,
        "messages_unacknowledged": 0,
        "messages": 99,
    }
    second = await provider.get_queue_depth(QUEUE_DIAGNOSTIC_NORMAL)

    assert first == second
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_rabbitmq_provider_fails_closed_without_cache() -> None:
    client = _RabbitHTTPClient()
    client.fail = True
    provider = RabbitMQQueueDepthProvider(
        settings=_rabbit_settings(),
        http_client=client,
    )

    with pytest.raises(QueueDepthUnavailable):
        await provider.get_queue_depth(QUEUE_DIAGNOSTIC_NORMAL)


@pytest.mark.asyncio
async def test_rabbitmq_provider_uses_valid_cache_on_temporary_failure() -> None:
    client = _RabbitHTTPClient()
    now = 100.0
    provider = RabbitMQQueueDepthProvider(
        settings=_rabbit_settings(ttl_seconds=10),
        http_client=client,
        monotonic=lambda: now,
    )

    first = await provider.get_queue_depth(QUEUE_DIAGNOSTIC_NORMAL)
    client.fail = True
    second = await provider.get_queue_depth(QUEUE_DIAGNOSTIC_NORMAL)

    assert second == first
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_admission_gate_uses_provider_depth() -> None:
    provider = _StaticDepthProvider(default_depth=21)

    decision = await AdmissionGate(
        redis_client=_AdmissionRedis(),
        thresholds=AdmissionGateThresholds(
            queue_depth_warn=10,
            queue_depth_reject=20,
        ),
        queue_depth_provider=provider,
    ).evaluate(queue_name=QUEUE_DIAGNOSTIC_NORMAL, tenant_id="tenant-depth")

    assert decision.outcome is AdmissionOutcome.REJECT
    assert decision.reason is AdmissionReason.QUEUE_DEPTH_EXCEEDED
    assert decision.queue_depth == 21


@pytest.mark.asyncio
async def test_health_reads_queue_depth_provider_counts() -> None:
    provider = _StaticDepthProvider(
        {
            QUEUE_DIAGNOSTIC_NORMAL: QueueDepthSample(
                queue_name=QUEUE_DIAGNOSTIC_NORMAL,
                depth=7,
                messages_ready=7,
                messages_unacknowledged=3,
                messages=10,
            )
        }
    )
    service = HealthService(
        settings=get_settings(),
        redis_provider=lambda: _AdmissionRedis(),  # type: ignore[arg-type]
        queue_depth_provider=provider,
    )

    response = HealthResponse.from_report(await service.health())

    queue = response.queues[QUEUE_DIAGNOSTIC_NORMAL]
    assert queue.depth == 7
    assert queue.messages_ready == 7
    assert queue.messages_unacknowledged == 3
    assert queue.messages == 10


@pytest.mark.asyncio
async def test_queue_status_reads_queue_depth_provider_counts() -> None:
    provider = _StaticDepthProvider(
        {
            QUEUE_DIAGNOSTIC_NORMAL: QueueDepthSample(
                queue_name=QUEUE_DIAGNOSTIC_NORMAL,
                depth=5,
                messages_ready=5,
                messages_unacknowledged=1,
                messages=6,
            )
        }
    )
    service = QueueOperationsService(
        session=cast(Any, object()),
        redis_provider=lambda: _AdmissionRedis(),  # type: ignore[arg-type]
        queue_depth_provider=provider,
    )

    response = QueueStatusResponse.from_record(await service.get_queue_status())

    queue = response.queues[QUEUE_DIAGNOSTIC_NORMAL]
    assert queue.depth == 5
    assert queue.oldest_age_seconds is None
    assert queue.messages_ready == 5
    assert queue.messages_unacknowledged == 1
    assert queue.messages == 6


def _rabbit_settings(*, ttl_seconds: int = 10) -> Settings:
    return Settings(
        QUEUE_DEPTH_BACKEND="rabbitmq",
        RABBITMQ_MANAGEMENT_API_URL="https://rabbit.example",
        RABBITMQ_MANAGEMENT_USERNAME="operator",
        RABBITMQ_MANAGEMENT_PASSWORD="password",
        RABBITMQ_MANAGEMENT_VHOST="/",
        RABBITMQ_DEPTH_CACHE_TTL_SECONDS=ttl_seconds,
    )

"""Broker-agnostic Celery queue-depth providers."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from inspect import isawaitable
from typing import Any, Literal, Protocol, cast
from urllib.parse import quote

from app.core.config import Settings, get_settings
from app.core.http import get_shared_http_client
from app.core.redis import get_redis_client

QueueDepthBackend = Literal["redis", "rabbitmq"]

_DEFAULT_RABBITMQ_TIMEOUT_SECONDS = 2.0
_queue_depth_provider: QueueDepthProvider | None = None


class RedisQueueDepthClient(Protocol):
    def llen(self, name: str) -> Awaitable[int] | int:
        ...


class QueueDepthProvider(Protocol):
    backend: QueueDepthBackend

    async def get_queue_depth(self, queue_name: str) -> "QueueDepthSample":
        ...


class QueueDepthHTTPResponse(Protocol):
    @property
    def status_code(self) -> int:
        ...

    @property
    def text(self) -> str:
        ...

    def json(self) -> Any:
        ...


class QueueDepthHTTPClient(Protocol):
    def get(
        self,
        url: str,
        *,
        auth: tuple[str, str],
        timeout: float,
    ) -> Awaitable[QueueDepthHTTPResponse] | QueueDepthHTTPResponse:
        ...


@dataclass(frozen=True, slots=True)
class QueueDepthSample:
    """Single broker queue-depth sample.

    ``depth`` is the admission-gating depth. For RabbitMQ this is
    ``messages_ready``; Redis only exposes the list length.
    """

    queue_name: str
    depth: int
    messages_ready: int | None = None
    messages_unacknowledged: int | None = None
    messages: int | None = None


class QueueDepthUnavailable(RuntimeError):
    """Raised when queue depth cannot be sampled from the configured backend."""


class RedisQueueDepthProvider:
    """Queue depth provider backed by Redis ``LLEN``."""

    backend: QueueDepthBackend = "redis"

    def __init__(self, redis_client: RedisQueueDepthClient) -> None:
        self._redis_client = redis_client

    async def get_queue_depth(self, queue_name: str) -> QueueDepthSample:
        depth = int(await _resolve(self._redis_client.llen(queue_name)) or 0)
        return QueueDepthSample(queue_name=queue_name, depth=depth)


@dataclass(frozen=True, slots=True)
class _RabbitMQCacheEntry:
    sample: QueueDepthSample
    expires_at: float


class RabbitMQQueueDepthProvider:
    """Queue depth provider backed by the RabbitMQ management HTTP API."""

    backend: QueueDepthBackend = "rabbitmq"

    def __init__(
        self,
        *,
        settings: Settings,
        http_client: QueueDepthHTTPClient | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._api_url = (settings.RABBITMQ_MANAGEMENT_API_URL or "").rstrip("/")
        self._username = settings.RABBITMQ_MANAGEMENT_USERNAME or ""
        self._password = settings.RABBITMQ_MANAGEMENT_PASSWORD or ""
        self._vhost = settings.RABBITMQ_MANAGEMENT_VHOST
        self._ttl_seconds = max(
            0.0,
            float(settings.RABBITMQ_DEPTH_CACHE_TTL_SECONDS),
        )
        self._http_client = http_client
        self._monotonic = monotonic
        self._cache: dict[str, _RabbitMQCacheEntry] = {}

    async def get_queue_depth(self, queue_name: str) -> QueueDepthSample:
        now = self._monotonic()
        cached = self._cache.get(queue_name)
        if cached is not None and cached.expires_at > now:
            return cached.sample
        try:
            sample = await self._fetch_queue_depth(queue_name)
        except Exception as exc:
            cached = self._cache.get(queue_name)
            if cached is not None and cached.expires_at > self._monotonic():
                return cached.sample
            if isinstance(exc, QueueDepthUnavailable):
                raise
            raise QueueDepthUnavailable("rabbitmq_queue_depth_unavailable") from exc
        self._cache[queue_name] = _RabbitMQCacheEntry(
            sample=sample,
            expires_at=self._monotonic() + self._ttl_seconds,
        )
        return sample

    async def _fetch_queue_depth(self, queue_name: str) -> QueueDepthSample:
        if not self._api_url or not self._username or not self._password:
            raise QueueDepthUnavailable("rabbitmq_management_not_configured")
        encoded_vhost = quote(self._vhost, safe="")
        encoded_queue = quote(queue_name, safe="")
        url = f"{self._api_url}/api/queues/{encoded_vhost}/{encoded_queue}"
        response = await _resolve(
            self._client().get(
                url,
                auth=(self._username, self._password),
                timeout=_DEFAULT_RABBITMQ_TIMEOUT_SECONDS,
            )
        )
        if response.status_code < 200 or response.status_code >= 300:
            raise QueueDepthUnavailable("rabbitmq_management_http_error")
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise QueueDepthUnavailable("rabbitmq_management_invalid_payload")
        body = cast(Mapping[str, object], payload)
        messages_ready = _required_int(body, "messages_ready")
        messages_unacknowledged = _required_int(
            body,
            "messages_unacknowledged",
        )
        messages = _required_int(body, "messages")
        return QueueDepthSample(
            queue_name=queue_name,
            depth=messages_ready,
            messages_ready=messages_ready,
            messages_unacknowledged=messages_unacknowledged,
            messages=messages,
        )

    def _client(self) -> QueueDepthHTTPClient:
        if self._http_client is not None:
            return self._http_client
        return cast(QueueDepthHTTPClient, get_shared_http_client())


def build_queue_depth_provider(
    *,
    settings: Settings,
    redis_client: RedisQueueDepthClient | None = None,
    http_client: QueueDepthHTTPClient | None = None,
) -> QueueDepthProvider:
    """Build a queue-depth provider from runtime settings."""

    if settings.QUEUE_DEPTH_BACKEND == "rabbitmq":
        return RabbitMQQueueDepthProvider(
            settings=settings,
            http_client=http_client,
        )
    return RedisQueueDepthProvider(redis_client or get_redis_client())


def get_queue_depth_provider() -> QueueDepthProvider:
    """Return the process-wide queue-depth provider, creating it lazily."""

    global _queue_depth_provider
    if _queue_depth_provider is None:
        _queue_depth_provider = build_queue_depth_provider(settings=get_settings())
    return _queue_depth_provider


def reset_queue_depth_provider() -> None:
    """Forget the cached provider after test settings or process reset."""

    global _queue_depth_provider
    _queue_depth_provider = None


async def _resolve(value: Awaitable[Any] | Any) -> Any:
    if isawaitable(value):
        return await value
    return value


def _required_int(payload: Mapping[str, object], key: str) -> int:
    value = payload.get(key)
    if value is None:
        raise QueueDepthUnavailable(f"rabbitmq_management_missing_{key}")
    try:
        if isinstance(value, bool):
            raise TypeError("boolean is not a queue depth")
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            return int(value)
        raise TypeError(f"unsupported queue depth type: {type(value).__name__}")
    except (TypeError, ValueError) as exc:
        raise QueueDepthUnavailable(
            f"rabbitmq_management_invalid_{key}"
        ) from exc


__all__ = [
    "QueueDepthBackend",
    "QueueDepthHTTPClient",
    "QueueDepthHTTPResponse",
    "QueueDepthProvider",
    "QueueDepthSample",
    "QueueDepthUnavailable",
    "RabbitMQQueueDepthProvider",
    "RedisQueueDepthClient",
    "RedisQueueDepthProvider",
    "build_queue_depth_provider",
    "get_queue_depth_provider",
    "reset_queue_depth_provider",
]

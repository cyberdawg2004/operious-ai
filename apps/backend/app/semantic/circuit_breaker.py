"""Sliding-window semantic circuit breaker."""

from __future__ import annotations

import base64
import logging
import struct
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from enum import Enum
from inspect import isawaitable
from typing import Protocol, TypeVar, cast

_REDIS_KEY_PREFIX = "semantic:circuit"
_WINDOW_SECONDS = 300
_CLUSTER_THRESHOLD = 5
_SIMILARITY_THRESHOLD = 0.7

_logger = logging.getLogger(__name__)
_T = TypeVar("_T")


class SemanticCircuitState(str, Enum):
    CLOSED = "CLOSED"
    TRIPPED = "TRIPPED"
    RESET = "RESET"


class SemanticCircuitRedisClient(Protocol):
    def zadd(
        self,
        name: str,
        mapping: Mapping[bytes, float],
        *,
        nx: bool = False,
    ) -> Awaitable[int] | int: ...

    def zremrangebyscore(
        self,
        name: str,
        min: int | float,
        max: int | float,
    ) -> Awaitable[int] | int: ...

    def zrange(
        self,
        name: str,
        start: int,
        end: int,
    ) -> Awaitable[Sequence[bytes | str]] | Sequence[bytes | str]: ...


class SemanticCircuitBreaker:
    """
    Per-tenant, per-channel sliding window cluster detector.
    Redis sorted set: scores = unix timestamp, values = serialized fingerprint.
    """

    def __init__(
        self,
        redis_client: SemanticCircuitRedisClient,
        *,
        window_seconds: int = _WINDOW_SECONDS,
        cluster_threshold: int = _CLUSTER_THRESHOLD,
        similarity_threshold: float = _SIMILARITY_THRESHOLD,
        time_provider: Callable[[], float] | None = None,
    ) -> None:
        if window_seconds < 1:
            raise ValueError("window_seconds must be >= 1")
        if cluster_threshold < 1:
            raise ValueError("cluster_threshold must be >= 1")
        if not 0.0 <= similarity_threshold <= 1.0:
            raise ValueError("similarity_threshold must be between 0 and 1")
        self._redis = redis_client
        self._window_seconds = window_seconds
        self._cluster_threshold = cluster_threshold
        self._similarity_threshold = similarity_threshold
        self._time_provider = time_provider or time.time

    @property
    def window_seconds(self) -> int:
        return self._window_seconds

    @property
    def similarity_threshold(self) -> float:
        return self._similarity_threshold

    async def evaluate(
        self,
        *,
        tenant_id: str,
        channel: str,
        ticket_id: str,
        fingerprint: tuple[int, ...],
    ) -> tuple[SemanticCircuitState, int]:
        """
        Returns (state, cluster_size).
        TRIPPED when cluster_size >= the configured cluster threshold.
        CLOSED on any Redis error (fail-open).
        """
        try:
            key = f"{_REDIS_KEY_PREFIX}:{tenant_id}:{channel}"
            now = self._time_provider()
            cutoff = now - self._window_seconds

            serialized = self._serialize(fingerprint)
            await _resolve(self._redis.zadd(key, {serialized: now}, nx=True))
            await _resolve(self._redis.zremrangebyscore(key, 0, cutoff))
            recent = await _resolve(self._redis.zrange(key, 0, -1))

            cluster_size = 0
            for entry in recent:
                entry_fp = self._deserialize(entry)
                similarity = self._jaccard(fingerprint, entry_fp)
                if similarity >= self._similarity_threshold:
                    cluster_size += 1

            state = (
                SemanticCircuitState.TRIPPED
                if cluster_size >= self._cluster_threshold
                else SemanticCircuitState.CLOSED
            )
            return (state, cluster_size)
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "semantic_circuit_eval_failed",
                extra={
                    "tenant_id": tenant_id,
                    "channel": channel,
                    "ticket_id": ticket_id,
                    "error": str(exc),
                },
            )
            return (SemanticCircuitState.CLOSED, 0)

    def _serialize(self, fp: tuple[int, ...]) -> bytes:
        packed = struct.pack(f"<{len(fp)}I", *fp)
        return base64.b64encode(packed)

    def _deserialize(self, data: bytes | str) -> tuple[int, ...]:
        packed = base64.b64decode(data, validate=True)
        count = len(packed) // 4
        return tuple(
            int(value)
            for value in cast(
                tuple[int, ...],
                struct.unpack(f"<{count}I", packed),
            )
        )

    def _jaccard(
        self,
        a: tuple[int, ...],
        b: tuple[int, ...],
    ) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        return sum(x == y for x, y in zip(a, b)) / len(a)


async def _resolve(value: Awaitable[_T] | _T) -> _T:
    if isawaitable(value):
        return await cast(Awaitable[_T], value)
    return value


__all__ = [
    "SemanticCircuitBreaker",
    "SemanticCircuitRedisClient",
    "SemanticCircuitState",
    "_CLUSTER_THRESHOLD",
    "_REDIS_KEY_PREFIX",
    "_SIMILARITY_THRESHOLD",
    "_WINDOW_SECONDS",
]

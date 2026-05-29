"""Distributed active voice-call capacity counter."""

from __future__ import annotations

import logging
from typing import Protocol

VOICE_CAPACITY_KEY = "voice:active_calls"
VOICE_CAPACITY_LIMIT = 100

_ACQUIRE_SCRIPT = """
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
local limit = tonumber(ARGV[1])
if current < limit then
    redis.call('INCR', KEYS[1])
    return 1
end
return 0
"""

_RELEASE_SCRIPT = """
local current = redis.call('GET', KEYS[1])
if current and tonumber(current) > 0 then
    return redis.call('DECR', KEYS[1])
end
return 0
"""

logger = logging.getLogger(__name__)


class VoiceCapacityRedisClient(Protocol):
    async def ping(self) -> object: ...

    async def eval(
        self,
        script: str,
        numkeys: int,
        *keys_and_args: object,
    ) -> object: ...

    async def get(self, name: str) -> object: ...


class VoiceCapacityCounter:
    """Redis-backed distributed active call counter."""

    def __init__(
        self,
        redis_client: VoiceCapacityRedisClient,
        limit: int = VOICE_CAPACITY_LIMIT,
        *,
        key: str = VOICE_CAPACITY_KEY,
    ) -> None:
        if limit <= 0:
            raise ValueError("VoiceCapacityCounter.limit must be > 0")
        self._redis = redis_client
        self._limit = limit
        self._key = key

    async def try_acquire(self) -> bool:
        try:
            result = await self._redis.eval(
                _ACQUIRE_SCRIPT,
                1,
                self._key,
                self._limit,
            )
        except Exception as exc:  # noqa: BLE001 - voice capacity fails closed.
            logger.warning(
                "voice_capacity_acquire_failed",
                extra={"error": exc.__class__.__name__},
            )
            return False
        return _coerce_int(result) == 1

    async def release(self) -> None:
        try:
            await self._redis.eval(_RELEASE_SCRIPT, 1, self._key)
        except Exception as exc:  # noqa: BLE001 - release is best-effort.
            logger.warning(
                "voice_capacity_release_failed",
                extra={"error": exc.__class__.__name__},
            )

    async def current_count(self) -> int:
        value = await self._redis.get(self._key)
        if value is None:
            return 0
        return max(0, _coerce_int(value))

    async def is_available(self) -> bool:
        try:
            await self._redis.ping()
            return True
        except Exception:
            return False


__all__ = [
    "VOICE_CAPACITY_KEY",
    "VOICE_CAPACITY_LIMIT",
    "VoiceCapacityCounter",
    "VoiceCapacityRedisClient",
]


def _coerce_int(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, bytes):
        return int(value.decode("utf-8"))
    if isinstance(value, str):
        return int(value)
    raise TypeError(f"cannot coerce {type(value).__name__} to int")

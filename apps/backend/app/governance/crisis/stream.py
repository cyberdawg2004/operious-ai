"""Redis-backed crisis intercept event stream helpers."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from datetime import datetime, timezone
from inspect import isawaitable
from typing import Any, Protocol, cast

from redis.asyncio import Redis

from app.governance.decisions import GovernanceDecision
from app.governance.policies.crisis import crisis_policy_name_from_decision

logger = logging.getLogger(__name__)


class _CrisisRedisPubSub(Protocol):
    async def subscribe(self, channel: str) -> object:
        ...

    async def get_message(
        self,
        *,
        ignore_subscribe_messages: bool,
        timeout: float,
    ) -> Mapping[str, object] | None:
        ...

    async def unsubscribe(self, channel: str) -> object:
        ...


class _CrisisRedisClient(Protocol):
    async def publish(self, channel: str, message: str) -> object:
        ...

    def pubsub(self) -> _CrisisRedisPubSub:
        ...


_CloseCallback = Callable[[], Awaitable[object] | object]


async def publish_crisis_intercept_event(
    *,
    redis_client: Redis,
    tenant_id: str,
    execution_id: str,
    decision: GovernanceDecision,
    category: str | None = None,
) -> None:
    """Publish a crisis intercept event when a crisis policy blocks work."""

    policy_name = crisis_policy_name_from_decision(decision)
    if policy_name is None:
        return
    event = {
        "type": "intercept",
        "execution_id": execution_id,
        "template": policy_name,
        "category": category,
        "reason": decision.reason,
        "intercepted_at": datetime.now(timezone.utc).isoformat(),
        "tenant_id": tenant_id,
    }
    try:
        client = cast(_CrisisRedisClient, redis_client)
        await client.publish(
            _channel(tenant_id),
            json.dumps(event, default=str, separators=(",", ":"), sort_keys=True),
        )
    except Exception as exc:  # noqa: BLE001 - ticker must not affect work.
        logger.warning(
            "crisis_intercept_publish_failed",
            extra={"tenant_id": tenant_id, "error": str(exc)},
        )


async def subscribe_crisis_intercept_events(
    *,
    redis_client: Redis,
    expected_tenant_id: str,
    timeout_seconds: int = 300,
) -> AsyncIterator[dict[str, Any]]:
    """Yield tenant-scoped crisis intercept events from Redis pub/sub."""

    client = cast(_CrisisRedisClient, redis_client)
    pubsub = client.pubsub()
    channel = _channel(expected_tenant_id)
    await pubsub.subscribe(channel)
    try:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=1.0,
            )
            if not message or message.get("type") != "message":
                continue
            event = _decode_event(message.get("data"))
            if event.get("tenant_id") != expected_tenant_id:
                continue
            yield event
    finally:
        await pubsub.unsubscribe(channel)
        close = cast(_CloseCallback | None, getattr(pubsub, "aclose", None))
        if close is None:
            close = cast(_CloseCallback | None, getattr(pubsub, "close", None))
        if close is not None:
            result = close()
            if isawaitable(result):
                await result


def _decode_event(raw: object) -> dict[str, Any]:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    if not isinstance(raw, str):
        return {}
    decoded = json.loads(raw)
    if isinstance(decoded, dict):
        return cast(dict[str, Any], decoded)
    return {}


def _channel(tenant_id: str) -> str:
    return f"crisis:intercept:{tenant_id}"


__all__ = [
    "publish_crisis_intercept_event",
    "subscribe_crisis_intercept_events",
]

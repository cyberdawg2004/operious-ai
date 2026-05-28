"""Redis-backed conversation event stream helpers."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator, Mapping
from typing import Any, cast

logger = logging.getLogger(__name__)


async def publish_conversation_event(
    *,
    redis_client: Any,
    session_id: str,
    event: Mapping[str, Any],
) -> None:
    """Publish one conversation event without affecting caller success."""

    try:
        channel = _channel(session_id)
        await redis_client.publish(
            channel,
            json.dumps(
                dict(event),
                default=str,
                separators=(",", ":"),
                sort_keys=True,
            ),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "stream_publish_failed",
            extra={"session_id": session_id, "error": str(exc)},
        )


async def subscribe_conversation_events(
    *,
    redis_client: Any,
    session_id: str,
    expected_tenant_id: str,
    timeout_seconds: int = 300,
) -> AsyncIterator[dict[str, Any]]:
    """Yield tenant-scoped conversation events from Redis pub/sub."""

    pubsub = redis_client.pubsub()
    channel = _channel(session_id)
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
            if (
                event.get("type") == "status"
                and event.get("phase") == "complete"
            ):
                break
    finally:
        await pubsub.unsubscribe(channel)
        close = getattr(pubsub, "aclose", None)
        if close is None:
            close = getattr(pubsub, "close", None)
        if close is not None:
            result = close()
            if hasattr(result, "__await__"):
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


def _channel(session_id: str) -> str:
    return f"conversation:{session_id}"


__all__ = [
    "publish_conversation_event",
    "subscribe_conversation_events",
]

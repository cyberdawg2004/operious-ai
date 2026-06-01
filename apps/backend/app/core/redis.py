"""Async Redis client.

A single shared `redis.asyncio.Redis` instance, built from `Settings`.
Sprint B only exercises it from the readiness probe; later sprints will
use it for caching, rate limiting, idempotency keys, and pub/sub.

We keep this module deliberately tiny — no abstractions over Redis until
there's a concrete second backend to abstract over.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import cast

from redis.asyncio import Redis

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)
_redis_client: Redis | None = None


def _build_redis(settings: Settings) -> Redis:
    socket_timeout = min(5.0, settings.SURVIVABILITY_READINESS_PROBE_TIMEOUT_SECONDS)
    redis_from_url = cast(Callable[..., Redis], getattr(Redis, "from_url"))
    return redis_from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
        socket_timeout=socket_timeout,
        socket_connect_timeout=socket_timeout,
        health_check_interval=30,
        retry_on_timeout=False,
    )


def get_redis_client() -> Redis:
    """Return the shared async Redis client, creating it lazily."""

    global _redis_client

    if _redis_client is None:
        settings = get_settings()
        logger.info(
            "redis_client_create_begin",
            extra={
                "environment": settings.ENVIRONMENT,
                "url_scheme": settings.redis_url.split(":", maxsplit=1)[0],
            },
        )
        _redis_client = _build_redis(settings)
        logger.info("redis_client_create_complete")
    return _redis_client


async def get_redis() -> Redis:
    """FastAPI dependency returning the shared async Redis client."""
    return get_redis_client()


async def close_redis() -> None:
    """Close the connection pool cleanly on shutdown."""

    global _redis_client

    if _redis_client is None:
        logger.info("redis_client_close_skipped")
        return

    logger.info("redis_client_close_begin")
    try:
        await asyncio.wait_for(_redis_client.aclose(), timeout=2.0)
    except TimeoutError:
        logger.warning("redis_client_close_timeout")
    except RuntimeError as exc:
        if "Event loop is closed" not in str(exc):
            raise
        logger.warning("redis_client_close_loop_closed")
    finally:
        _redis_client = None
        logger.info("redis_client_close_complete")


__all__ = ["get_redis_client", "get_redis", "close_redis"]

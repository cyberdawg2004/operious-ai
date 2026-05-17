"""Async Redis client.

A single shared `redis.asyncio.Redis` instance, built from `Settings`.
Sprint B only exercises it from the readiness probe; later sprints will
use it for caching, rate limiting, idempotency keys, and pub/sub.

We keep this module deliberately tiny — no abstractions over Redis until
there's a concrete second backend to abstract over.
"""

from __future__ import annotations

from redis.asyncio import Redis, from_url

from app.core.config import Settings, get_settings


def _build_redis(settings: Settings) -> Redis:
    return from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
        socket_timeout=5,
        socket_connect_timeout=5,
        health_check_interval=30,
    )


_settings = get_settings()

redis_client: Redis = _build_redis(_settings)


async def get_redis() -> Redis:
    """FastAPI dependency returning the shared async Redis client."""
    return redis_client


async def close_redis() -> None:
    """Close the connection pool cleanly on shutdown."""
    await redis_client.aclose()


__all__ = ["redis_client", "get_redis", "close_redis"]

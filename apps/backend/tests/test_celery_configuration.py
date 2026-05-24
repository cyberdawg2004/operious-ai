"""Celery and Redis startup configuration invariants."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from app.core.redis_policy import verify_redis_memory_policy
from app.workers.celery_app import celery_app


class _ConfigRedis:
    def __init__(self, config: Mapping[str, Any]) -> None:
        self.config = config

    async def config_get(self, pattern: str = "*") -> Mapping[str, Any]:
        del pattern
        return self.config


class _RestrictedConfigRedis:
    async def config_get(self, pattern: str = "*") -> Mapping[str, Any]:
        del pattern
        raise RuntimeError("ERR unknown command 'CONFIG'")


def test_broker_connection_retry_on_startup_is_explicit() -> None:
    assert celery_app.conf.broker_connection_retry_on_startup is True


def test_backend_container_runs_as_non_root_celery_user() -> None:
    dockerfile = Path(__file__).parents[1] / "Dockerfile"
    text = dockerfile.read_text(encoding="utf-8")

    assert "addgroup --system celery" in text
    assert "adduser --system --ingroup celery celery" in text
    assert "\nUSER celery\n" in text


@pytest.mark.asyncio
async def test_redis_memory_policy_logs_ok_when_expected(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)

    result = await verify_redis_memory_policy(
        redis_client=_ConfigRedis({"maxmemory-policy": "allkeys-lru"}),
        expected_policy="allkeys-lru",
    )

    assert result.valid is True
    assert result.status == "ok"
    assert result.observed_policy == "allkeys-lru"
    assert "redis_memory_policy_ok" in caplog.text


@pytest.mark.asyncio
async def test_redis_memory_policy_logs_unverifiable_for_config_restriction(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)

    result = await verify_redis_memory_policy(
        redis_client=_RestrictedConfigRedis(),
        expected_policy="allkeys-lru",
    )

    assert result.valid is False
    assert result.status == "unverifiable"
    assert result.reason == "config_get_unavailable"
    assert result.observed_policy is None
    assert "redis_memory_policy_unverifiable" in caplog.text
    assert "redis_memory_policy_misconfigured" not in caplog.text


@pytest.mark.asyncio
async def test_redis_memory_policy_logs_misconfigured_for_bad_value(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR)

    result = await verify_redis_memory_policy(
        redis_client=_ConfigRedis({"maxmemory-policy": "noeviction"}),
        expected_policy="allkeys-lru",
    )

    assert result.valid is False
    assert result.status == "misconfigured"
    assert result.reason == "policy_mismatch"
    assert result.observed_policy == "noeviction"
    assert "redis_memory_policy_misconfigured" in caplog.text

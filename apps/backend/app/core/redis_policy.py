"""Redis operational policy checks."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class RedisConfigClient(Protocol):
    async def config_get(self, pattern: str = "*") -> Mapping[str, Any]:
        ...


@dataclass(frozen=True, slots=True)
class RedisMemoryPolicyCheck:
    expected_policy: str
    observed_policy: str | None
    valid: bool
    reason: str | None = None


async def verify_redis_memory_policy(
    *,
    redis_client: RedisConfigClient,
    expected_policy: str,
    check_logger: logging.Logger | None = None,
) -> RedisMemoryPolicyCheck:
    """Warn when Redis is not configured for bounded broker memory pressure."""

    log = check_logger or logger
    try:
        config = await redis_client.config_get("maxmemory-policy")
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "redis_memory_policy_check_failed",
            extra={"error_type": exc.__class__.__name__},
        )
        return RedisMemoryPolicyCheck(
            expected_policy=expected_policy,
            observed_policy=None,
            valid=False,
            reason="config_get_failed",
        )
    observed = _policy_from_config(config)
    if observed != expected_policy:
        log.warning(
            "redis_memory_policy_misconfigured",
            extra={
                "expected_policy": expected_policy,
                "observed_policy": observed,
            },
        )
        return RedisMemoryPolicyCheck(
            expected_policy=expected_policy,
            observed_policy=observed,
            valid=False,
            reason="policy_mismatch",
        )
    log.info(
        "redis_memory_policy_verified",
        extra={"expected_policy": expected_policy},
    )
    return RedisMemoryPolicyCheck(
        expected_policy=expected_policy,
        observed_policy=observed,
        valid=True,
    )


def _policy_from_config(config: Mapping[str, Any]) -> str | None:
    value = config.get("maxmemory-policy")
    if isinstance(value, str):
        return value
    for key, item in config.items():
        if str(key).lower() == "maxmemory-policy":
            return str(item)
    return None


__all__ = [
    "RedisConfigClient",
    "RedisMemoryPolicyCheck",
    "verify_redis_memory_policy",
]

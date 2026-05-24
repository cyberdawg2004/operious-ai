"""Redis operational policy checks."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol

logger = logging.getLogger(__name__)


RedisMemoryPolicyStatus = Literal["ok", "unverifiable", "misconfigured"]


class RedisConfigClient(Protocol):
    async def config_get(self, pattern: str = "*") -> Mapping[str, Any]:
        ...


@dataclass(frozen=True, slots=True)
class RedisMemoryPolicyCheck:
    expected_policy: str
    observed_policy: str | None
    valid: bool
    reason: str | None = None
    status: RedisMemoryPolicyStatus = "ok"


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
        _log_unverifiable(
            log,
            expected_policy=expected_policy,
            reason="config_get_unavailable",
            error_type=exc.__class__.__name__,
        )
        return RedisMemoryPolicyCheck(
            expected_policy=expected_policy,
            observed_policy=None,
            valid=False,
            reason="config_get_unavailable",
            status="unverifiable",
        )
    observed = _policy_from_config(config)
    if observed is None:
        _log_unverifiable(
            log,
            expected_policy=expected_policy,
            reason="policy_missing",
            error_type=None,
        )
        return RedisMemoryPolicyCheck(
            expected_policy=expected_policy,
            observed_policy=None,
            valid=False,
            reason="policy_missing",
            status="unverifiable",
        )
    if observed != expected_policy:
        log.error(
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
            status="misconfigured",
        )
    log.info(
        "redis_memory_policy_ok",
        extra={"expected_policy": expected_policy, "observed_policy": observed},
    )
    return RedisMemoryPolicyCheck(
        expected_policy=expected_policy,
        observed_policy=observed,
        valid=True,
        status="ok",
    )


def _log_unverifiable(
    log: logging.Logger,
    *,
    expected_policy: str,
    reason: str,
    error_type: str | None,
) -> None:
    log.warning(
        "redis_memory_policy_unverifiable",
        extra={
            "expected_policy": expected_policy,
            "reason": reason,
            "error_type": error_type,
            "manual_action": (
                "Upstash requires maxmemory-policy to be configured in the "
                "dashboard; Redis CONFIG SET cannot change it."
            ),
            "dashboard_path": "Upstash Console > Database > Configuration",
        },
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
    "RedisMemoryPolicyStatus",
    "verify_redis_memory_policy",
]

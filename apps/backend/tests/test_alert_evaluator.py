"""PR_T8 alert evaluator coverage."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, cast

import pytest
from sqlalchemy import text

from app.core.admission import admission_thresholds_from_settings
from app.core.config import Settings
from app.execution.db.models import ExecutionRow
from app.hardening.admission import AdmissionGate
from app.hardening.admission.gate import AdmissionRedisClient
from app.hardening.observability import alert_evaluator as alert_module
from app.hardening.observability.alert_evaluator import (
    AlertEvaluator,
    AlertResult,
)
from app.queues import QUEUE_DIAGNOSTIC_NORMAL
from app.runtime.db.models import DeadLetterTaskRow, ProviderCircuitStateRow
from app.runtime.provider_circuit_breaker import ProviderCircuitState
from app.semantic.db.models import SemanticCircuitEventRow
from app.tenant.db.models import TenantRow
from tests.conftest import requires_postgres

TENANT_ID = "tenant-alert-evaluator"


@pytest.mark.asyncio
async def test_queue_age_breach_fires_alert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _RedisFake(queue_ages={QUEUE_DIAGNOSTIC_NORMAL: 601})

    results = await _evaluator(redis=redis)._check_queue_age_slo()

    assert [result.resource for result in results] == [QUEUE_DIAGNOSTIC_NORMAL]
    assert results[0].condition_name == "queue_age_slo_breach"


@pytest.mark.asyncio
async def test_queue_age_ok_does_not_fire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _RedisFake(queue_ages={QUEUE_DIAGNOSTIC_NORMAL: 60})

    results = await _evaluator(redis=redis)._check_queue_age_slo()

    assert results == []


@requires_postgres
@pytest.mark.asyncio
async def test_dlq_spike_fires_when_count_increases(
    pg_seed_session: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del monkeypatch
    before_count = await _recent_dlq_count(pg_seed_session)
    for index in range(7):
        await _seed_dead_letter(
            pg_seed_session,
            tenant_id=f"{TENANT_ID}-dlq-spike",
            seed=f"spike-{index}-{uuid.uuid4()}",
        )
    redis = _RedisFake(values={"alert:dlq_baseline": str(before_count)})

    results = await _evaluator(
        redis=redis,
        owner_session=pg_seed_session,
    )._check_dlq_spike(pg_seed_session)

    assert [result.condition_name for result in results] == ["dlq_spike"]
    assert results[0].metadata["delta"] >= 5
    assert redis.values["alert:dlq_baseline"] == str(
        await _recent_dlq_count(pg_seed_session)
    )


@requires_postgres
@pytest.mark.asyncio
async def test_dlq_no_spike_when_count_stable(
    pg_seed_session: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del monkeypatch
    before_count = await _recent_dlq_count(pg_seed_session)
    await _seed_dead_letter(
        pg_seed_session,
        tenant_id=f"{TENANT_ID}-dlq-stable",
        seed=f"stable-{uuid.uuid4()}",
    )
    redis = _RedisFake(values={"alert:dlq_baseline": str(before_count)})

    results = await _evaluator(
        redis=redis,
        owner_session=pg_seed_session,
    )._check_dlq_spike(pg_seed_session)

    assert results == []
    assert redis.values["alert:dlq_baseline"] == str(
        await _recent_dlq_count(pg_seed_session)
    )


@requires_postgres
@pytest.mark.asyncio
async def test_provider_circuit_open_fires_alert(
    pg_seed_session: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del monkeypatch
    tenant_id = f"{TENANT_ID}-circuit"
    provider = "anthropic"
    now = datetime.now(timezone.utc)
    await pg_seed_session.merge(TenantRow(tenant_id=tenant_id))
    await pg_seed_session.flush()
    pg_seed_session.add(
        ProviderCircuitStateRow(
            state_id=uuid.uuid5(uuid.NAMESPACE_URL, f"{tenant_id}:{provider}"),
            tenant_id=tenant_id,
            provider_name=provider,
            state=ProviderCircuitState.OPEN.value,
            consecutive_failures=3,
            retry_count=0,
            retry_window_started_at=None,
            opened_at=now,
            open_until=None,
            half_open_trial_started_at=None,
            last_failure_reason="rate_limit",
            last_transition_at=now,
            updated_at=now,
            metadata_json={},
        )
    )
    await pg_seed_session.flush()

    results = await _evaluator(owner_session=pg_seed_session)._check_provider_circuits(
        pg_seed_session
    )

    assert len(results) == 1
    assert results[0].condition_name == "provider_circuit_open"
    assert results[0].dedup_key == f"circuit_open:{tenant_id}:{provider}"


@pytest.mark.asyncio
async def test_redis_memory_fires_above_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _RedisFake(used_memory=90, maxmemory=100)

    results = await _evaluator(redis=redis)._check_redis_memory()

    assert [result.condition_name for result in results] == [
        "redis_memory_pressure"
    ]


@pytest.mark.asyncio
async def test_redis_memory_ok_below_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _RedisFake(used_memory=60, maxmemory=100)

    results = await _evaluator(redis=redis)._check_redis_memory()

    assert results == []


@pytest.mark.asyncio
async def test_db_pool_exhaustion_fires_alert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del monkeypatch

    results = await _evaluator(
        engine=_EngineFake(_PoolFake(checked_out=9, size=10, overflow=0))
    )._check_db_pool()

    assert [result.condition_name for result in results] == ["db_pool_exhaustion"]
    assert results[0].metadata["utilization"] == 0.9


@pytest.mark.asyncio
async def test_db_pool_check_skips_nullpool() -> None:
    results = await _evaluator(
        settings=_settings(DB_USE_NULLPOOL=True)
    )._check_db_pool()

    assert results == []


@pytest.mark.asyncio
async def test_alert_not_refired_within_cooldown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _RedisFake()
    sentry_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        alert_module.sentry_sdk,
        "capture_message",
        lambda message, *, level: sentry_calls.append((message, level)),
    )
    evaluator = _evaluator(redis=redis)
    result = _alert_result()

    await evaluator._fire_alert(result, None)  # type: ignore[arg-type]
    await evaluator._fire_alert(result, None)  # type: ignore[arg-type]

    assert sentry_calls == [("[warning] queue old", "warning")]
    assert redis.values["alert:cooldown:queue_age:diagnostic.normal"] == "1"


@pytest.mark.asyncio
async def test_alert_refires_after_cooldown_expires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _RedisFake()
    sentry_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        alert_module.sentry_sdk,
        "capture_message",
        lambda message, *, level: sentry_calls.append((message, level)),
    )
    evaluator = _evaluator(redis=redis)
    result = _alert_result()

    await evaluator._fire_alert(result, None)  # type: ignore[arg-type]
    redis.values.pop("alert:cooldown:queue_age:diagnostic.normal")
    await evaluator._fire_alert(result, None)  # type: ignore[arg-type]

    assert sentry_calls == [
        ("[warning] queue old", "warning"),
        ("[warning] queue old", "warning"),
    ]


@pytest.mark.asyncio
async def test_one_condition_failure_does_not_block_others(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evaluator = _evaluator()
    seen: list[str] = []

    async def raises() -> list[AlertResult]:
        seen.append("queue")
        raise RuntimeError("boom")

    async def no_results() -> list[AlertResult]:
        seen.append("no_results")
        return []

    async def no_results_with_session(_session: Any) -> list[AlertResult]:
        seen.append("with_session")
        return []

    async def memory_result() -> list[AlertResult]:
        seen.append("memory")
        return [_alert_result(condition_name="redis_memory_pressure")]

    monkeypatch.setattr(evaluator, "_check_queue_age_slo", raises)
    monkeypatch.setattr(evaluator, "_check_dlq_spike", no_results_with_session)
    monkeypatch.setattr(evaluator, "_check_provider_circuits", no_results_with_session)
    monkeypatch.setattr(
        evaluator,
        "_check_semantic_circuit_tripped",
        no_results_with_session,
    )
    monkeypatch.setattr(evaluator, "_check_redis_memory", memory_result)
    monkeypatch.setattr(evaluator, "_check_db_pool", no_results)
    monkeypatch.setattr(evaluator, "_check_replay_mismatch", no_results_with_session)

    results = await evaluator.evaluate_all(None)  # type: ignore[arg-type]

    assert [result.condition_name for result in results] == [
        "redis_memory_pressure"
    ]
    assert seen == [
        "queue",
        "with_session",
        "with_session",
        "with_session",
        "memory",
        "no_results",
        "with_session",
    ]


@pytest.mark.asyncio
async def test_evaluator_skips_when_redis_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evaluator = _evaluator(redis=_RedisUnavailable())

    async def no_results() -> list[AlertResult]:
        return []

    async def no_results_with_session(_session: Any) -> list[AlertResult]:
        return []

    monkeypatch.setattr(evaluator, "_check_dlq_spike", no_results_with_session)
    monkeypatch.setattr(evaluator, "_check_provider_circuits", no_results_with_session)
    monkeypatch.setattr(
        evaluator,
        "_check_semantic_circuit_tripped",
        no_results_with_session,
    )
    monkeypatch.setattr(evaluator, "_check_db_pool", no_results)
    monkeypatch.setattr(evaluator, "_check_replay_mismatch", no_results_with_session)

    results = await evaluator.evaluate_all(None)  # type: ignore[arg-type]

    assert results == []


@pytest.mark.asyncio
async def test_capture_message_called_on_alert_fire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _RedisFake()
    sentry_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        alert_module.sentry_sdk,
        "capture_message",
        lambda message, *, level: sentry_calls.append((message, level)),
    )

    await _evaluator(redis=redis)._fire_alert(
        _alert_result(
            condition_name="provider_circuit_open",
            severity="critical",
            message="circuit open",
            dedup_key="circuit_open:tenant:anthropic",
        ),
        None,  # type: ignore[arg-type]
    )

    assert sentry_calls == [("[critical] circuit open", "error")]


@pytest.mark.asyncio
async def test_alert_logged_on_alert_fire(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    caplog.set_level(logging.WARNING, logger=alert_module.__name__)
    redis = _RedisFake()
    monkeypatch.setattr(
        alert_module.sentry_sdk,
        "capture_message",
        lambda message, *, level: None,
    )

    await _evaluator(redis=redis)._fire_alert(
        _alert_result(),
        None,  # type: ignore[arg-type]
    )

    assert "alert.fired" in caplog.text


@requires_postgres
@pytest.mark.asyncio
async def test_replay_mismatch_fires_when_execution_missing(
    pg_seed_session: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del monkeypatch
    tenant_id = f"{TENANT_ID}-replay"
    execution_id = uuid.uuid4()
    row = await _seed_dead_letter(
        pg_seed_session,
        tenant_id=tenant_id,
        seed=f"replay-{uuid.uuid4()}",
        replayed=True,
        metadata={
            "celery_kwargs": {
                "execution_id": str(execution_id),
                "tenant_id": tenant_id,
            },
        },
    )

    results = await _evaluator(owner_session=pg_seed_session)._check_replay_mismatch(
        pg_seed_session
    )

    assert [result.condition_name for result in results] == ["replay_mismatch"]
    assert results[0].dedup_key == f"replay_mismatch:{row.dead_letter_task_id}"


@requires_postgres
@pytest.mark.asyncio
async def test_replay_mismatch_ignores_rows_without_execution_id(
    pg_seed_session: Any,
) -> None:
    await _seed_dead_letter(
        pg_seed_session,
        tenant_id=f"{TENANT_ID}-replay-no-execution",
        seed=f"replay-no-execution-{uuid.uuid4()}",
        replayed=True,
        metadata={"celery_kwargs": {"tenant_id": TENANT_ID}},
    )

    results = await _evaluator(owner_session=pg_seed_session)._check_replay_mismatch(
        pg_seed_session
    )

    assert results == []


def _settings(**overrides: Any) -> Settings:
    return Settings(
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        SENTRY_DSN="",
        **overrides,
    )


def _alert_result(
    *,
    condition_name: str = "queue_age_slo_breach",
    severity: str = "warning",
    message: str = "queue old",
    dedup_key: str = "queue_age:diagnostic.normal",
) -> AlertResult:
    return AlertResult(
        condition_name=condition_name,
        fired=True,
        severity=severity,
        message=message,
        resource=QUEUE_DIAGNOSTIC_NORMAL,
        dedup_key=dedup_key,
        metadata={"queue_name": QUEUE_DIAGNOSTIC_NORMAL},
    )


def _evaluator(
    *,
    redis: Any | None = None,
    owner_session: Any | None = None,
    engine: Any | None = None,
    settings: Settings | None = None,
) -> AlertEvaluator:
    selected_settings = settings or _settings()
    selected_redis = redis or _RedisFake()
    selected_engine = engine or _EngineFake(
        _PoolFake(checked_out=0, size=10, overflow=0)
    )

    def admission_gate_factory() -> AdmissionGate:
        return AdmissionGate(
            redis_client=cast(AdmissionRedisClient, selected_redis),
            thresholds=admission_thresholds_from_settings(selected_settings),
        )

    return AlertEvaluator(
        settings=selected_settings,
        redis_provider=lambda: selected_redis,
        admission_gate_factory=admission_gate_factory,
        owner_session_context_factory=lambda: _OwnerSessionContext(owner_session),
        engine_provider=lambda: selected_engine,
        queue_names=(QUEUE_DIAGNOSTIC_NORMAL,),
        dead_letter_task_row=DeadLetterTaskRow,
        provider_circuit_state_row=ProviderCircuitStateRow,
        semantic_circuit_event_row=SemanticCircuitEventRow,
        execution_row=ExecutionRow,
        provider_open_state=ProviderCircuitState.OPEN.value,
    )


async def _recent_dlq_count(session: Any) -> int:
    return int(
        (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM dead_letter_tasks "
                    "WHERE created_at > NOW() - INTERVAL '1 hour'"
                )
            )
        ).scalar_one()
        or 0
    )


async def _seed_dead_letter(
    session: Any,
    *,
    tenant_id: str,
    seed: str,
    replayed: bool = False,
    metadata: Mapping[str, Any] | None = None,
) -> DeadLetterTaskRow:
    await session.merge(TenantRow(tenant_id=tenant_id))
    await session.flush()
    now = datetime.now(timezone.utc)
    row = DeadLetterTaskRow(
        dead_letter_task_id=uuid.uuid5(uuid.NAMESPACE_URL, f"alert-dlq:{seed}"),
        tenant_id=tenant_id,
        task_name="execute_diagnostic_agent",
        task_id=f"task-alert-{seed}",
        execution_id=None,
        queue=QUEUE_DIAGNOSTIC_NORMAL,
        reason="retry budget exhausted",
        retry_count=3,
        created_at=now,
        replayed=replayed,
        replayed_at=now if replayed else None,
        replayed_by="operator-principal" if replayed else None,
        metadata_json=dict(metadata or {}),
    )
    session.add(row)
    await session.flush()
    return row


class _RedisFake:
    def __init__(
        self,
        *,
        queue_ages: Mapping[str, float] | None = None,
        used_memory: int = 0,
        maxmemory: int = 0,
        values: Mapping[str, str] | None = None,
    ) -> None:
        self.queue_ages = dict(queue_ages or {})
        self.used_memory = used_memory
        self.maxmemory = maxmemory
        self.values = dict(values or {})

    async def info(self, section: str | None = None) -> dict[str, int]:
        del section
        return {
            "used_memory": self.used_memory,
            "maxmemory": self.maxmemory,
        }

    async def llen(self, name: str) -> int:
        del name
        return 0

    async def zrange(
        self,
        name: str,
        start: int,
        end: int,
        *,
        withscores: bool = False,
    ) -> list[tuple[str, float]]:
        del start, end
        if not withscores:
            return []
        queue_name = name.removeprefix("queue:age:")
        age = self.queue_ages.get(queue_name)
        if age is None:
            return []
        return [("member", time.time() - age)]

    async def exists(self, key: str) -> int:
        return int(key in self.values)

    async def set(
        self,
        key: str,
        value: str,
        *,
        ex: int | None = None,
    ) -> bool:
        del ex
        self.values[key] = value
        return True

    async def get(self, key: str) -> str | None:
        return self.values.get(key)


class _RedisUnavailable:
    async def info(self, section: str | None = None) -> dict[str, int]:
        del section
        raise RuntimeError("redis unavailable")

    async def llen(self, name: str) -> int:
        del name
        raise RuntimeError("redis unavailable")

    async def zrange(
        self,
        name: str,
        start: int,
        end: int,
        *,
        withscores: bool = False,
    ) -> list[tuple[str, float]]:
        del name, start, end, withscores
        raise RuntimeError("redis unavailable")

    async def exists(self, key: str) -> int:
        del key
        raise RuntimeError("redis unavailable")

    async def set(
        self,
        key: str,
        value: str,
        *,
        ex: int | None = None,
    ) -> bool:
        del key, value, ex
        raise RuntimeError("redis unavailable")

    async def get(self, key: str) -> str | None:
        del key
        raise RuntimeError("redis unavailable")


class _OwnerSessionContext:
    def __init__(self, session: Any) -> None:
        self._session = session

    async def __aenter__(self) -> Any:
        return self._session

    async def __aexit__(
        self,
        exc_type: object,
        exc: object,
        traceback: object,
    ) -> None:
        del exc_type, exc, traceback


class _OwnerSessionFactory:
    def __init__(self, session: Any) -> None:
        self._session = session

    def __call__(self) -> _OwnerSessionContext:
        return _OwnerSessionContext(self._session)


class _PoolFake:
    def __init__(self, *, checked_out: int, size: int, overflow: int) -> None:
        self._checked_out = checked_out
        self._size = size
        self._overflow = overflow

    def checkedout(self) -> int:
        return self._checked_out

    def size(self) -> int:
        return self._size

    def overflow(self) -> int:
        return self._overflow


class _SyncEngineFake:
    def __init__(self, pool: _PoolFake) -> None:
        self.pool = pool


class _EngineFake:
    def __init__(self, pool: _PoolFake) -> None:
        self.sync_engine = _SyncEngineFake(pool)

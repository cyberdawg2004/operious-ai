"""Phase D provider circuit-breaker hardening tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.execution import InMemoryExecutionPersistence
from app.governance.persistence import InMemoryGovernanceRepository
from app.runtime import (
    ExecutionGovernanceRuntime,
    ProviderCircuitBreaker,
    ProviderCircuitOpenError,
    ProviderCircuitState,
)
from app.tenant.enums import TenantExecutionGovernanceStatus
from app.tenant.persistence import InMemoryTenantConfigurationRepository
from app.tenant.runtime import TenantConfigurationRuntime
from tests.conftest import approved_record

TENANT_ID = "tenant-provider-circuit"
PROVIDER = "anthropic"
NOW = datetime(2026, 5, 23, 12, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_circuit_half_open_trial_request_recloses_on_success() -> None:
    breaker = ProviderCircuitBreaker(default_open_seconds=30)
    await breaker.open(
        tenant_id=TENANT_ID,
        provider_name=PROVIDER,
        reason="rate_limit",
        open_until=NOW,
        now=NOW - timedelta(seconds=30),
    )

    trial = await breaker.before_request(
        tenant_id=TENANT_ID,
        provider_name=PROVIDER,
        now=NOW + timedelta(seconds=1),
    )
    assert trial.state is ProviderCircuitState.HALF_OPEN
    assert trial.half_open_trial_started_at == NOW + timedelta(seconds=1)

    with pytest.raises(ProviderCircuitOpenError):
        await breaker.before_request(
            tenant_id=TENANT_ID,
            provider_name=PROVIDER,
            now=NOW + timedelta(seconds=2),
        )

    closed = await breaker.record_success(
        tenant_id=TENANT_ID,
        provider_name=PROVIDER,
        now=NOW + timedelta(seconds=3),
    )
    assert closed.state is ProviderCircuitState.CLOSED
    assert closed.consecutive_failures == 0
    assert closed.open_until is None


@pytest.mark.asyncio
async def test_retry_budget_exhaustion_opens_circuit() -> None:
    breaker = ProviderCircuitBreaker(retry_budget_per_minute=5)

    for index in range(6):
        snapshot = await breaker.consume_retry_budget(
            tenant_id=TENANT_ID,
            provider_name=PROVIDER,
            now=NOW + timedelta(seconds=index),
        )

    assert snapshot.state is ProviderCircuitState.OPEN
    assert snapshot.last_failure_reason == "retry_budget_exhausted"
    assert snapshot.open_until is not None
    assert snapshot.open_until > NOW


@pytest.mark.asyncio
async def test_execution_governance_denies_when_provider_circuit_open() -> None:
    tenant_repo = InMemoryTenantConfigurationRepository()
    await TenantConfigurationRuntime(repository=tenant_repo).configure_execution_governance(
        tenant_id=TENANT_ID,
        execution_quota=100,
        throughput_limit=100,
        throughput_window_minutes=60,
        governance_budget_limit=100,
        governance_budget_window_minutes=60,
        circuit_failure_threshold=100,
        circuit_window_minutes=60,
        circuit_cooldown_minutes=5,
        configured_by="principal-ops",
        status=TenantExecutionGovernanceStatus.ACTIVE,
        approval=approved_record(
            tenant_id=TENANT_ID,
            target_id="execution-governance",
            seed="provider-circuit",
        ),
    )
    breaker = ProviderCircuitBreaker()
    opened = await breaker.open(
        tenant_id=TENANT_ID,
        provider_name=PROVIDER,
        reason="rate_limit",
        open_until=NOW + timedelta(minutes=5),
        now=NOW,
    )
    runtime = ExecutionGovernanceRuntime(
        tenant_configuration_repository=tenant_repo,
        execution_persistence=InMemoryExecutionPersistence(),
        governance_repository=InMemoryGovernanceRepository(),
        provider_circuit_breaker=breaker,
    )

    evaluation = await runtime.evaluate(
        tenant_id=TENANT_ID,
        provider_name=PROVIDER,
        now=NOW + timedelta(seconds=1),
    )

    assert not evaluation.allowed
    assert evaluation.reason == "execution_governance:provider_circuit_open"
    assert evaluation.provider_circuit_state == opened.state.value
    assert opened.open_until is not None
    assert evaluation.metadata["provider_open_until"] == opened.open_until.isoformat()

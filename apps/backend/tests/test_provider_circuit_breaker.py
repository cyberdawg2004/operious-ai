"""Phase D provider circuit-breaker hardening tests."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.execution import InMemoryExecutionPersistence
from app.governance.persistence import InMemoryGovernanceRepository
from app.runtime import (
    ExecutionGovernanceRuntime,
    ProviderCircuitBreaker,
    ProviderCircuitOpenError,
    ProviderCircuitState,
)
from app.runtime.provider_circuit_breaker import ProviderCircuitSnapshot
from app.tenant.enums import TenantExecutionGovernanceStatus
from app.tenant.persistence import InMemoryTenantConfigurationRepository
from app.tenant.runtime import TenantConfigurationRuntime
from tests.conftest import approved_record, requires_postgres, set_pg_rls_tenant

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


@pytest.mark.asyncio
@requires_postgres
async def test_postgres_get_state_concurrent_creation_is_idempotent(
    pg_engine: AsyncEngine,
) -> None:
    tenant_id = f"tenant-provider-circuit-{uuid.uuid4().hex[:12]}"
    provider = "operious-deterministic-llm"
    session_factory = async_sessionmaker(
        pg_engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )

    async with pg_engine.begin() as connection:
        await connection.execute(
            text("INSERT INTO tenants (tenant_id) VALUES (:t) ON CONFLICT DO NOTHING"),
            {"t": tenant_id},
        )

    snapshot = ProviderCircuitSnapshot(
        state_id=uuid.uuid5(uuid.NAMESPACE_URL, f"{tenant_id}|{provider}"),
        tenant_id=tenant_id,
        provider_name=provider,
        state=ProviderCircuitState.CLOSED,
        consecutive_failures=0,
        retry_count=0,
        retry_window_started_at=None,
        opened_at=None,
        open_until=None,
        half_open_trial_started_at=None,
        last_failure_reason=None,
        last_transition_at=NOW,
        updated_at=NOW,
        metadata={"origin": "test"},
    )

    async def create_state() -> None:
        async with session_factory() as session:
            await set_pg_rls_tenant(session, tenant_id)
            await ProviderCircuitBreaker(
                session=session,
                auto_commit=True,
            )._save(snapshot)  # pyright: ignore[reportPrivateUsage]

    try:
        await asyncio.gather(*(create_state() for _ in range(8)))
        async with pg_engine.connect() as connection:
            count = (
                await connection.execute(
                    text(
                        """
                        SELECT count(*)
                        FROM provider_circuit_states
                        WHERE tenant_id = :t AND provider_name = :provider
                        """
                    ),
                    {"t": tenant_id, "provider": provider},
                )
            ).scalar_one()
        assert count == 1
    finally:
        async with pg_engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM provider_circuit_states WHERE tenant_id = :t"),
                {"t": tenant_id},
            )
            await connection.execute(
                text("DELETE FROM tenants WHERE tenant_id = :t"),
                {"t": tenant_id},
            )

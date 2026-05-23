"""Execution governance admission runtime."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from app.execution.enums import ExecutionState
from app.execution.persistence import (
    ExecutionPersistenceProtocol,
    ExecutionQuery,
)
from app.governance.persistence import BaseGovernanceRepository, DecisionQuery
from app.tenant.enums import TenantExecutionCircuitState
from app.tenant.identity import derive_execution_circuit_breaker_id
from app.tenant.persistence import (
    TenantConfigurationRepository,
    TenantExecutionCircuitBreakerRecord,
    TenantExecutionGovernanceConfigurationRecord,
)
from app.runtime.provider_circuit_breaker import (
    ProviderCircuitBreaker,
    ProviderCircuitState,
)

_EVALUATION_NAMESPACE = uuid.UUID("f64a9df2-76aa-5a1a-81a8-45c21f448be0")


@dataclass(frozen=True, slots=True)
class ExecutionGovernanceEvaluation:
    evaluation_id: uuid.UUID
    evaluated_at: datetime
    allowed: bool
    reason: str | None
    config: TenantExecutionGovernanceConfigurationRecord | None
    circuit_breaker: TenantExecutionCircuitBreakerRecord | None
    metadata: Mapping[str, Any]
    provider_circuit_state: str | None = None

    @property
    def degraded(self) -> bool:
        return not self.allowed


class ExecutionGovernanceRuntime:
    """Admission gate that must precede durable execution creation."""

    def __init__(
        self,
        *,
        tenant_configuration_repository: TenantConfigurationRepository,
        execution_persistence: ExecutionPersistenceProtocol,
        governance_repository: BaseGovernanceRepository,
        provider_circuit_breaker: ProviderCircuitBreaker | None = None,
        default_provider_name: str | None = None,
    ) -> None:
        self._tenant_configuration_repository = tenant_configuration_repository
        self._execution_persistence = execution_persistence
        self._governance_repository = governance_repository
        self._provider_circuit_breaker = provider_circuit_breaker
        self._default_provider_name = default_provider_name

    async def evaluate(
        self,
        *,
        tenant_id: str,
        now: datetime | None = None,
        provider_name: str | None = None,
    ) -> ExecutionGovernanceEvaluation:
        evaluated_at = now or datetime.now(timezone.utc)
        effective_provider_name = provider_name or self._default_provider_name
        evaluation_id = _evaluation_id(
            tenant_id, evaluated_at, effective_provider_name
        )
        config = (
            await self._tenant_configuration_repository.resolve_active_execution_governance_configuration(
                expected_tenant_id=tenant_id,
            )
        )
        if config is None:
            return ExecutionGovernanceEvaluation(
                evaluation_id=evaluation_id,
                evaluated_at=evaluated_at,
                allowed=False,
                reason="execution_governance:configuration_missing",
                config=None,
                circuit_breaker=None,
                metadata={"configuration": "missing"},
            )

        provider_circuit_state: str | None = None
        if (
            effective_provider_name is not None
            and self._provider_circuit_breaker is not None
        ):
            provider_circuit = await self._provider_circuit_breaker.get_state(
                tenant_id=tenant_id,
                provider_name=effective_provider_name,
                now=evaluated_at,
            )
            provider_circuit_state = provider_circuit.state.value
            if (
                provider_circuit.state is ProviderCircuitState.OPEN
                and (
                    provider_circuit.open_until is None
                    or provider_circuit.open_until > evaluated_at
                )
            ):
                return _deny(
                    evaluation_id=evaluation_id,
                    evaluated_at=evaluated_at,
                    reason="execution_governance:provider_circuit_open",
                    config=config,
                    breaker=None,
                    metadata={
                        "provider_name": effective_provider_name,
                        "provider_circuit_state": provider_circuit.state.value,
                        "provider_open_until": (
                            provider_circuit.open_until.isoformat()
                            if provider_circuit.open_until is not None
                            else None
                        ),
                    },
                    provider_circuit_state=provider_circuit.state.value,
                )

        breaker = await self._load_or_create_breaker(
            tenant_id=tenant_id,
            config=config,
            now=evaluated_at,
        )
        if (
            breaker.state is TenantExecutionCircuitState.OPEN
            and breaker.open_until is not None
            and breaker.open_until > evaluated_at
        ):
            return _deny(
                evaluation_id=evaluation_id,
                evaluated_at=evaluated_at,
                reason="execution_governance:circuit_open",
                config=config,
                breaker=breaker,
                metadata={"circuit_state": breaker.state.value},
            )

        execution_page = await self._execution_persistence.list_executions(
            ExecutionQuery(tenant_id=tenant_id, limit=1),
            expected_tenant_id=tenant_id,
        )
        if execution_page.total >= config.execution_quota:
            return _deny(
                evaluation_id=evaluation_id,
                evaluated_at=evaluated_at,
                reason="execution_governance:execution_quota_exceeded",
                config=config,
                breaker=breaker,
                metadata={"execution_count": execution_page.total},
            )

        throughput_start = evaluated_at - timedelta(
            minutes=config.throughput_window_minutes
        )
        throughput_page = await self._execution_persistence.list_executions(
            ExecutionQuery(
                tenant_id=tenant_id,
                requested_after_or_at=throughput_start,
                limit=1,
            ),
            expected_tenant_id=tenant_id,
        )
        throughput_count = throughput_page.total
        if throughput_count >= config.throughput_limit:
            return _deny(
                evaluation_id=evaluation_id,
                evaluated_at=evaluated_at,
                reason="execution_governance:throughput_limit_exceeded",
                config=config,
                breaker=breaker,
                metadata={"throughput_count": throughput_count},
            )

        budget_start = evaluated_at - timedelta(
            minutes=config.governance_budget_window_minutes
        )
        budget_page = await self._governance_repository.query_decisions(
            DecisionQuery(
                tenant_id=tenant_id,
                decided_after_or_at=budget_start,
                limit=1,
            )
        )
        governance_budget_used = budget_page.total
        if governance_budget_used > config.governance_budget_limit:
            return _deny(
                evaluation_id=evaluation_id,
                evaluated_at=evaluated_at,
                reason="execution_governance:governance_budget_exceeded",
                config=config,
                breaker=breaker,
                metadata={"governance_budget_used": governance_budget_used},
            )

        failure_start = evaluated_at - timedelta(minutes=config.circuit_window_minutes)
        failure_page = await self._execution_persistence.list_executions(
            ExecutionQuery(
                tenant_id=tenant_id,
                state=ExecutionState.FAILED,
                failed_after_or_at=failure_start,
                limit=1,
            ),
            expected_tenant_id=tenant_id,
        )
        failure_count = failure_page.total
        if failure_count >= config.circuit_failure_threshold:
            opened = await self._save_breaker(
                breaker=TenantExecutionCircuitBreakerRecord(
                    breaker_id=breaker.breaker_id,
                    tenant_id=tenant_id,
                    config_id=config.config_id,
                    state=TenantExecutionCircuitState.OPEN,
                    failure_count=failure_count,
                    opened_at=evaluated_at,
                    open_until=evaluated_at
                    + timedelta(minutes=config.circuit_cooldown_minutes),
                    last_transition_at=evaluated_at,
                    reason="execution_governance:circuit_opened",
                    updated_at=evaluated_at,
                    metadata={"failure_count": failure_count},
                )
            )
            return _deny(
                evaluation_id=evaluation_id,
                evaluated_at=evaluated_at,
                reason="execution_governance:circuit_opened",
                config=config,
                breaker=opened,
                metadata={"failure_count": failure_count},
            )

        return ExecutionGovernanceEvaluation(
            evaluation_id=evaluation_id,
            evaluated_at=evaluated_at,
            allowed=True,
            reason=None,
            config=config,
            circuit_breaker=breaker,
            metadata={"configuration": "active"},
            provider_circuit_state=provider_circuit_state,
        )

    async def _load_or_create_breaker(
        self,
        *,
        tenant_id: str,
        config: TenantExecutionGovernanceConfigurationRecord,
        now: datetime,
    ) -> TenantExecutionCircuitBreakerRecord:
        breaker_id = derive_execution_circuit_breaker_id(
            tenant_id=tenant_id,
            config_id=config.config_id,
        )
        breaker = await self._tenant_configuration_repository.get_execution_circuit_breaker(
            breaker_id,
            expected_tenant_id=tenant_id,
        )
        if breaker is not None:
            return breaker
        return await self._save_breaker(
            breaker=TenantExecutionCircuitBreakerRecord(
                breaker_id=breaker_id,
                tenant_id=tenant_id,
                config_id=config.config_id,
                state=TenantExecutionCircuitState.CLOSED,
                failure_count=0,
                opened_at=None,
                open_until=None,
                last_transition_at=now,
                reason=None,
                updated_at=now,
                metadata={"origin": "execution_governance_runtime"},
            )
        )

    async def _save_breaker(
        self,
        *,
        breaker: TenantExecutionCircuitBreakerRecord,
    ) -> TenantExecutionCircuitBreakerRecord:
        await self._tenant_configuration_repository.save_execution_circuit_breaker(
            breaker,
            expected_tenant_id=breaker.tenant_id,
        )
        return breaker


def _deny(
    *,
    evaluation_id: uuid.UUID,
    evaluated_at: datetime,
    reason: str,
    config: TenantExecutionGovernanceConfigurationRecord,
    breaker: TenantExecutionCircuitBreakerRecord | None,
    metadata: Mapping[str, Any],
    provider_circuit_state: str | None = None,
) -> ExecutionGovernanceEvaluation:
    return ExecutionGovernanceEvaluation(
        evaluation_id=evaluation_id,
        evaluated_at=evaluated_at,
        allowed=False,
        reason=reason,
        config=config,
        circuit_breaker=breaker,
        metadata=dict(metadata),
        provider_circuit_state=provider_circuit_state,
    )


def _evaluation_id(
    tenant_id: str,
    evaluated_at: datetime,
    provider_name: str | None,
) -> uuid.UUID:
    return uuid.uuid5(
        _EVALUATION_NAMESPACE,
        f"{tenant_id}|{evaluated_at.isoformat()}|{provider_name or ''}",
    )


__all__ = ["ExecutionGovernanceEvaluation", "ExecutionGovernanceRuntime"]

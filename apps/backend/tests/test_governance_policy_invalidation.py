"""Governance policy invalidation regression tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, ClassVar, FrozenSet, Sequence

import pytest

from app.governance.context import GovernanceContext
from app.governance.decisions import PolicyEvaluationResult
from app.governance.enforcement.handlers import (
    AllowHandler,
    DegradeHandler,
    DenyHandler,
    EnforcementHandlerRegistry,
    EscalateHandler,
    RedactHandler,
    RequireApprovalHandler,
)
from app.governance.enforcement.runtime import GovernanceRuntime
from app.governance.enums import Decision, EnforcementStage, ViolationSeverity
from app.governance.evaluators.engine import PolicyEvaluationEngine
from app.governance.policies.base import BaseGovernancePolicy
from app.governance.policies.chain import PolicyChain
from app.governance.subjects.base import GenericGovernanceSubject
from app.identity import TenantId
from app.services.tenant_configuration_service import TenantConfigurationService
from app.tenant.enums import TenantGovernancePolicyStatus
from app.tenant.persistence import (
    InMemoryTenantConfigurationRepository,
    TenantGovernancePolicyQuery,
)
from app.tenant.runtime import TenantConfigurationRuntime


class _FixedPolicy(BaseGovernancePolicy):
    supported_stages: ClassVar[FrozenSet[EnforcementStage]] = frozenset(
        {EnforcementStage.PRE_REQUEST}
    )

    def __init__(self, *, name: str, decision: Decision) -> None:
        self._name = name
        self._decision = decision

    @property
    def name(self) -> str:  # type: ignore[override]
        return self._name

    async def evaluate(
        self, context: GovernanceContext
    ) -> Sequence[PolicyEvaluationResult]:
        return (
            PolicyEvaluationResult(
                policy_name=self._name,
                rule_id="fixed",
                decision=self._decision,
                severity=ViolationSeverity.MEDIUM,
                reason=f"fixed {self._decision.value}",
            ),
        )


class _CommitSession:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class _PublishingRedis:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def publish(self, channel: str, message: str) -> int:
        self.calls.append((channel, message))
        return 1


class _FailingRedis:
    async def publish(self, channel: str, message: str) -> int:
        del channel, message
        raise ConnectionError("redis unavailable")


def _handler_registry() -> EnforcementHandlerRegistry:
    registry = EnforcementHandlerRegistry()
    for handler in (
        AllowHandler(),
        DenyHandler(),
        RedactHandler(),
        DegradeHandler(),
        EscalateHandler(),
        RequireApprovalHandler(),
    ):
        registry.register(handler)
    return registry


def _chain(decision: Decision) -> PolicyChain:
    return PolicyChain(
        chain_id=f"test.{decision.value}",
        stage=EnforcementStage.PRE_REQUEST,
        policies=(
            _FixedPolicy(name=f"test.{decision.value}", decision=decision),
        ),
    )


def _runtime(decision: Decision) -> GovernanceRuntime:
    return GovernanceRuntime(
        engine=PolicyEvaluationEngine(),
        handler_registry=_handler_registry(),
        chains={EnforcementStage.PRE_REQUEST: _chain(decision)},
    )


def _context() -> GovernanceContext:
    return GovernanceContext(
        stage=EnforcementStage.PRE_REQUEST,
        action="test.governance",
        resource="tenant:tenant-acme/resource:test",
        actor="tester",
        tenant_id=TenantId("tenant-acme"),
        subject=GenericGovernanceSubject(data={"kind": "test"}),
    )


def _service(
    *,
    redis_client: Any,
    repository: InMemoryTenantConfigurationRepository | None = None,
) -> tuple[
    TenantConfigurationService,
    InMemoryTenantConfigurationRepository,
    _CommitSession,
]:
    repo = repository or InMemoryTenantConfigurationRepository()
    session = _CommitSession()
    service = TenantConfigurationService(
        runtime=TenantConfigurationRuntime(repository=repo),
        session=session,  # type: ignore[arg-type]
        redis_client=redis_client,
    )
    return service, repo, session


async def _create_policy(
    service: TenantConfigurationService,
    *,
    decision: Decision,
) -> Any:
    return await service.create_governance_policy(
        tenant_id="tenant-acme",
        policy_type="runtime_decision",
        parameters={"decision": decision.value},
        status=TenantGovernancePolicyStatus.ACTIVE,
        approved_by="principal-a",
        effective_from=datetime(2026, 5, 29, tzinfo=timezone.utc),
    )


async def _runtime_from_policy_repository(
    repository: InMemoryTenantConfigurationRepository,
) -> GovernanceRuntime:
    page = await repository.list_governance_policies(
        TenantGovernancePolicyQuery(policy_type="runtime_decision"),
        expected_tenant_id="tenant-acme",
    )
    record = max(page.items, key=lambda item: item.version)
    decision = Decision(str(record.parameters["decision"]))
    return _runtime(decision)


@pytest.mark.asyncio
async def test_replace_chains_updates_runtime() -> None:
    runtime = _runtime(Decision.ALLOW)
    first = await runtime.evaluate(_context())
    assert first.unwrap().decision is Decision.ALLOW

    runtime.replace_chains({EnforcementStage.PRE_REQUEST: _chain(Decision.DENY)})

    second = await runtime.evaluate(_context())
    assert second.unwrap().decision is Decision.DENY


@pytest.mark.asyncio
async def test_policy_write_publishes_invalidation_signal() -> None:
    redis = _PublishingRedis()
    service, _, session = _service(redis_client=redis)

    await _create_policy(service, decision=Decision.ALLOW)

    assert session.commits == 1
    assert len(redis.calls) == 1
    channel, message = redis.calls[0]
    assert channel == "governance:policy:invalidate:tenant-acme"
    assert json.loads(message)["tenant_id"] == "tenant-acme"


@pytest.mark.asyncio
async def test_publish_failure_does_not_block_policy_write() -> None:
    service, repo, session = _service(redis_client=_FailingRedis())

    record = await _create_policy(service, decision=Decision.ALLOW)

    assert session.commits == 1
    stored = await repo.get_governance_policy(
        record.policy_id,
        expected_tenant_id="tenant-acme",
    )
    assert stored is not None
    assert stored.policy_id == record.policy_id


@pytest.mark.asyncio
async def test_per_task_runtime_sees_updated_policy_at_construction() -> None:
    redis = _PublishingRedis()
    service, repo, _ = _service(redis_client=redis)

    first_policy = await _create_policy(service, decision=Decision.ALLOW)
    first_runtime = await _runtime_from_policy_repository(repo)
    assert (await first_runtime.evaluate(_context())).unwrap().decision is Decision.ALLOW

    await service.update_governance_policy(
        tenant_id="tenant-acme",
        policy_id=first_policy.policy_id,
        parameters={"decision": Decision.DENY.value},
        status=TenantGovernancePolicyStatus.ACTIVE,
        approved_by="principal-b",
        effective_from=None,
    )
    next_runtime = await _runtime_from_policy_repository(repo)

    assert (await next_runtime.evaluate(_context())).unwrap().decision is Decision.DENY

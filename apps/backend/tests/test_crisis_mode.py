"""Crisis-mode governance tests."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.governance.context import GovernanceContext
from app.governance.crisis import CrisisDeploymentScope, CrisisTemplate
from app.governance.db.models import CrisisDeploymentRow
from app.governance.enums import Decision, EnforcementStage
from app.governance.policies.crisis import (
    CrisisBlockSKUPolicy,
    CrisisEscalateAllPolicy,
    _crisis_key,
)
from app.governance.subjects.execution import ExecutionGovernanceSubject
from app.identity import TenantId
from app.services.crisis_service import CrisisService


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.deleted: list[str] = []

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

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

    async def delete(self, key: str) -> int:
        self.deleted.append(key)
        existed = key in self.values
        self.values.pop(key, None)
        return 1 if existed else 0


class _FailingRedis(_FakeRedis):
    async def get(self, key: str) -> str | None:
        del key
        raise ConnectionError("redis unavailable")


def _context(
    *,
    tenant_id: str = "tenant-a",
    query: str = "customer asks about SKU A3219",
    category: str = "charging_issue",
) -> GovernanceContext:
    return GovernanceContext(
        stage=EnforcementStage.PRE_EXECUTION,
        action="ai.diagnostic_classification",
        resource="execution:test",
        actor="agent:diagnostic",
        tenant_id=TenantId(tenant_id),
        subject=ExecutionGovernanceSubject(
            query=query,
            tenant_id=tenant_id,
            execution_action="ai.diagnostic_classification",
            metadata={"category": category},
        ),
    )


@pytest.mark.asyncio
async def test_crisis_policy_dormant_when_key_absent() -> None:
    result = await CrisisEscalateAllPolicy(redis=_FakeRedis()).evaluate(_context())

    assert result[0].decision is Decision.ALLOW


@pytest.mark.asyncio
async def test_crisis_policy_fires_when_key_present() -> None:
    redis = _FakeRedis()
    await redis.set(_crisis_key("tenant-a", "escalate_all"), "{}")

    result = await CrisisEscalateAllPolicy(redis=redis).evaluate(_context())

    assert result[0].decision is Decision.ESCALATE
    assert result[0].policy_name == "crisis.escalate_all"


@pytest.mark.asyncio
async def test_block_sku_only_matches_target_sku() -> None:
    redis = _FakeRedis()
    await redis.set(_crisis_key("tenant-a", "block_sku", "A3219"), "{}")
    policy = CrisisBlockSKUPolicy(redis=redis)

    blocked = await policy.evaluate(_context(query="charger A3219 failed"))
    allowed = await policy.evaluate(_context(query="charger B1234 failed"))

    assert blocked[0].decision is Decision.DENY
    assert allowed[0].decision is Decision.ALLOW


@pytest.mark.asyncio
async def test_deploy_sets_redis_key(
    crisis_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with crisis_session_factory() as session:
        redis = _FakeRedis()
        record = await _service(session, redis).deploy(
            tenant_id="tenant-a",
            expected_tenant_id="tenant-a",
            template=CrisisTemplate.BLOCK_SKU,
            scope=CrisisDeploymentScope(
                template=CrisisTemplate.BLOCK_SKU,
                sku="A3219",
            ),
            ttl_minutes=30,
            deployed_by="principal-a",
        )

        assert record.redis_key == _crisis_key("tenant-a", "block_sku", "A3219")
        assert record.redis_key in redis.values
        stored = await session.get(
            CrisisDeploymentRow,
            uuid.UUID(record.deployment_id),
        )
        assert stored is not None
        assert stored.status == "active"


@pytest.mark.asyncio
async def test_deactivate_deletes_redis_key(
    crisis_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with crisis_session_factory() as session:
        redis = _FakeRedis()
        service = _service(session, redis)
        record = await service.deploy(
            tenant_id="tenant-a",
            expected_tenant_id="tenant-a",
            template=CrisisTemplate.ESCALATE_ALL,
            scope=CrisisDeploymentScope(template=CrisisTemplate.ESCALATE_ALL),
            ttl_minutes=0,
            deployed_by="principal-a",
        )

        deactivated = await service.deactivate(
            deployment_id=record.deployment_id,
            deactivated_by="principal-a",
            tenant_id="tenant-a",
            expected_tenant_id="tenant-a",
        )

        assert deactivated.status == "deactivated"
        assert record.redis_key not in redis.values
        assert record.redis_key in redis.deleted


@pytest.mark.asyncio
async def test_dry_run_sets_no_keys(
    crisis_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with crisis_session_factory() as session:
        redis = _FakeRedis()
        record = await _service(session, redis).deploy(
            tenant_id="tenant-a",
            expected_tenant_id="tenant-a",
            template=CrisisTemplate.HALT_REFUNDS,
            scope=CrisisDeploymentScope(template=CrisisTemplate.HALT_REFUNDS),
            ttl_minutes=30,
            deployed_by="principal-a",
            dry_run=True,
        )

        assert record.status == "preview"
        assert redis.values == {}
        assert await session.get(
            CrisisDeploymentRow,
            uuid.UUID(record.deployment_id),
        ) is None


@pytest.mark.asyncio
async def test_ttl_expiry_marks_expired(
    crisis_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with crisis_session_factory() as session:
        service = _service(session, _FakeRedis())
        record = await service.deploy(
            tenant_id="tenant-a",
            expected_tenant_id="tenant-a",
            template=CrisisTemplate.FREEZE_CATEGORY,
            scope=CrisisDeploymentScope(
                template=CrisisTemplate.FREEZE_CATEGORY,
                category="refund_issue",
            ),
            ttl_minutes=1,
            deployed_by="principal-a",
        )
        row = await session.get(CrisisDeploymentRow, uuid.UUID(record.deployment_id))
        assert row is not None
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=2)
        await session.commit()

        expired_count = await service.expire_due()

        assert expired_count == 1
        refreshed = await session.get(
            CrisisDeploymentRow,
            uuid.UUID(record.deployment_id),
        )
        assert refreshed is not None
        assert refreshed.status == "expired"


@pytest.mark.asyncio
async def test_crisis_fail_open_on_redis_error() -> None:
    result = await CrisisEscalateAllPolicy(redis=_FailingRedis()).evaluate(_context())

    assert result[0].decision is Decision.ALLOW


@pytest.mark.asyncio
async def test_crisis_tenant_isolation(
    crisis_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with crisis_session_factory() as session:
        service = _service(session, _FakeRedis())
        await service.deploy(
            tenant_id="tenant-a",
            expected_tenant_id="tenant-a",
            template=CrisisTemplate.ESCALATE_ALL,
            scope=CrisisDeploymentScope(template=CrisisTemplate.ESCALATE_ALL),
            ttl_minutes=0,
            deployed_by="principal-a",
        )

        tenant_b = await service.list_active(
            tenant_id="tenant-b",
            expected_tenant_id="tenant-b",
        )

        assert tenant_b == []


def _service(session: AsyncSession, redis: Any) -> CrisisService:
    return CrisisService(session=session, redis_client=redis)


@pytest_asyncio.fixture
async def crisis_session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                CREATE TABLE crisis_deployments (
                    deployment_id CHAR(36) NOT NULL PRIMARY KEY,
                    tenant_id VARCHAR(255) NOT NULL,
                    template VARCHAR(64) NOT NULL,
                    scope_json JSON NOT NULL DEFAULT '{}',
                    ttl_minutes INTEGER NOT NULL DEFAULT 0,
                    policy_id CHAR(36),
                    deployed_by VARCHAR(255) NOT NULL,
                    deployed_at DATETIME NOT NULL,
                    expires_at DATETIME,
                    status VARCHAR(32) NOT NULL DEFAULT 'active',
                    metadata JSON NOT NULL DEFAULT '{}'
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE crisis_events (
                    event_id CHAR(36) NOT NULL PRIMARY KEY,
                    tenant_id VARCHAR(255) NOT NULL,
                    deployment_id CHAR(36) NOT NULL,
                    event_kind VARCHAR(32) NOT NULL,
                    template VARCHAR(64) NOT NULL,
                    scope_json JSON NOT NULL DEFAULT '{}',
                    ttl_minutes INTEGER NOT NULL DEFAULT 0,
                    actor VARCHAR(255) NOT NULL,
                    occurred_at DATETIME NOT NULL,
                    metadata JSON NOT NULL DEFAULT '{}'
                )
                """
            )
        )
    try:
        yield async_sessionmaker(
            bind=engine,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
            class_=AsyncSession,
        )
    finally:
        await engine.dispose()

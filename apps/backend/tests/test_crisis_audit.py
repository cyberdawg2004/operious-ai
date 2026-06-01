"""Crisis audit trail tests."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.v1.routers.crisis import router as crisis_router
from app.dependencies.authority import (
    require_tenant_operations_read,
    require_tenant_scope,
)
from app.dependencies.services import get_crisis_service
from app.events import (
    InMemoryOperationalEventPersistence,
    OperationalEventQuery,
    OperationalEventRuntime,
    OperationalSubstrate,
)
from app.governance.capability.acts import OperationalAct
from app.governance.crisis import CrisisDeploymentScope, CrisisTemplate
from app.governance.db.models import CrisisDeploymentRow, CrisisEventRow
from app.identity import AuthorityContext
from app.services.crisis_events import (
    CrisisEventRecord,
    PostgresCrisisEventRepository,
)
from app.services.crisis_service import CrisisService


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

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
        existed = key in self.values
        self.values.pop(key, None)
        return 1 if existed else 0


@pytest.mark.asyncio
async def test_deploy_writes_deployed_event(
    crisis_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with crisis_session_factory() as session:
        record = await _service(session).deploy(
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

        events = await _events(session, "tenant-a")

        assert len(events) == 1
        assert events[0].event_kind == "deployed"
        assert events[0].template == "block_sku"
        assert events[0].actor == "principal-a"
        assert str(events[0].deployment_id) == record.deployment_id


@pytest.mark.asyncio
async def test_crisis_deploy_emits_event(
    crisis_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    event_store = InMemoryOperationalEventPersistence()
    async with crisis_session_factory() as session:
        record = await _service(
            session,
            event_runtime=OperationalEventRuntime(persistence=event_store),
        ).deploy(
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

    page = await event_store.list_events(
        OperationalEventQuery(
            operational_act=OperationalAct.GOVERNANCE_CRISIS_DEPLOY,
            substrate=OperationalSubstrate.GOVERNANCE,
        ),
        expected_tenant_id="tenant-a",
    )

    assert page.total == 1
    event = page.events[0]
    assert event.metadata["_schema_version"] == "1"
    assert event.metadata["deployment_id"] == record.deployment_id
    assert event.metadata["template"] == "block_sku"
    assert event.metadata["ttl_minutes"] == 30


@pytest.mark.asyncio
async def test_deactivate_writes_deactivated_event(
    crisis_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with crisis_session_factory() as session:
        service = _service(session)
        record = await service.deploy(
            tenant_id="tenant-a",
            expected_tenant_id="tenant-a",
            template=CrisisTemplate.ESCALATE_ALL,
            scope=CrisisDeploymentScope(template=CrisisTemplate.ESCALATE_ALL),
            ttl_minutes=0,
            deployed_by="principal-a",
        )

        await service.deactivate(
            deployment_id=record.deployment_id,
            deactivated_by="principal-b",
            tenant_id="tenant-a",
            expected_tenant_id="tenant-a",
        )
        events = await _events(session, "tenant-a")

        assert [event.event_kind for event in events] == ["deactivated", "deployed"]
        assert events[0].actor == "principal-b"


@pytest.mark.asyncio
async def test_expiry_writes_expired_event(
    crisis_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with crisis_session_factory() as session:
        service = _service(session)
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
        events = await _events(session, "tenant-a")

        assert expired_count == 1
        assert events[0].event_kind == "expired"
        assert events[0].actor == "system"


@pytest.mark.asyncio
async def test_crisis_events_append_only(
    crisis_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with crisis_session_factory() as session:
        event = _event("tenant-a")
        await PostgresCrisisEventRepository(session).write(event)
        await session.commit()

        with pytest.raises(Exception):  # noqa: BLE001 - DB-specific append-only error.
            await session.execute(
                text(
                    """
                    UPDATE crisis_events
                    SET actor = 'mutated'
                    """
                )
            )
            await session.commit()
        await session.rollback()

        with pytest.raises(Exception):  # noqa: BLE001 - DB-specific append-only error.
            await session.execute(text("DELETE FROM crisis_events"))
            await session.commit()


@pytest.mark.asyncio
async def test_crisis_events_api_ordered_desc(
    crisis_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with crisis_session_factory() as session:
        repo = PostgresCrisisEventRepository(session)
        older = _event(
            "tenant-a",
            event_kind="deployed",
            occurred_at=datetime(2026, 5, 30, 1, tzinfo=timezone.utc),
        )
        newer = _event(
            "tenant-a",
            event_kind="deactivated",
            occurred_at=datetime(2026, 5, 30, 2, tzinfo=timezone.utc),
        )
        await repo.write(older)
        await repo.write(newer)
        await session.commit()

        async with _events_client(_service(session), "tenant-a") as client:
            response = await client.get("/api/v1/governance/crisis/events")

        assert response.status_code == 200
        payload = response.json()
        assert [item["event_id"] for item in payload["items"]] == [
            newer.event_id,
            older.event_id,
        ]


@pytest.mark.asyncio
async def test_crisis_events_tenant_isolation(
    crisis_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with crisis_session_factory() as session:
        await PostgresCrisisEventRepository(session).write(_event("tenant-a"))
        await session.commit()

        async with _events_client(_service(session), "tenant-b") as client:
            response = await client.get("/api/v1/governance/crisis/events")

        assert response.status_code == 200
        assert response.json()["items"] == []


@pytest.mark.asyncio
async def test_sentry_called_on_deploy(
    crisis_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def _capture_message(message: str, **kwargs: Any) -> None:
        calls.append({"message": message, **kwargs})

    monkeypatch.setattr(
        "app.services.crisis_service.sentry_sdk.capture_message",
        _capture_message,
    )

    async with crisis_session_factory() as session:
        await _service(session).deploy(
            tenant_id="tenant-a",
            expected_tenant_id="tenant-a",
            template=CrisisTemplate.HALT_REFUNDS,
            scope=CrisisDeploymentScope(template=CrisisTemplate.HALT_REFUNDS),
            ttl_minutes=30,
            deployed_by="principal-a",
        )

    assert calls
    assert calls[0]["level"] == "warning"
    assert "halt_refunds" in calls[0]["message"]


@pytest.mark.asyncio
async def test_sentry_failure_does_not_block_deploy(
    crisis_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _capture_message(message: str, **kwargs: Any) -> None:
        del message, kwargs
        raise RuntimeError("sentry unavailable")

    monkeypatch.setattr(
        "app.services.crisis_service.sentry_sdk.capture_message",
        _capture_message,
    )

    async with crisis_session_factory() as session:
        record = await _service(session).deploy(
            tenant_id="tenant-a",
            expected_tenant_id="tenant-a",
            template=CrisisTemplate.ESCALATE_ALL,
            scope=CrisisDeploymentScope(template=CrisisTemplate.ESCALATE_ALL),
            ttl_minutes=0,
            deployed_by="principal-a",
        )

    assert record.status == "active"


def _service(
    session: AsyncSession,
    redis: _FakeRedis | None = None,
    event_runtime: OperationalEventRuntime | None = None,
) -> CrisisService:
    return CrisisService(
        session=session,
        redis_client=redis or _FakeRedis(),
        event_repository=PostgresCrisisEventRepository(session),
        event_runtime=event_runtime,
    )


async def _events(session: AsyncSession, tenant_id: str) -> list[CrisisEventRow]:
    result = await session.scalars(
        select(CrisisEventRow)
        .where(CrisisEventRow.tenant_id == tenant_id)
        .order_by(CrisisEventRow.occurred_at.desc())
    )
    return list(result.all())


def _event(
    tenant_id: str,
    *,
    event_kind: str = "deployed",
    occurred_at: datetime | None = None,
) -> CrisisEventRecord:
    deployment_id = str(uuid.uuid4())
    return CrisisEventRecord(
        event_id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        deployment_id=deployment_id,
        event_kind=event_kind,
        template="escalate_all",
        scope_json={"template": "escalate_all"},
        ttl_minutes=0,
        actor="principal-a",
        occurred_at=occurred_at or datetime.now(timezone.utc),
        metadata={},
    )


def _events_client(
    service: CrisisService,
    tenant_id: str,
) -> httpx.AsyncClient:
    app = FastAPI()
    app.include_router(crisis_router, prefix="/api/v1/governance/crisis")
    app.dependency_overrides[get_crisis_service] = lambda: service
    app.dependency_overrides[require_tenant_scope] = lambda: tenant_id
    app.dependency_overrides[require_tenant_operations_read] = lambda: (
        AuthorityContext(
            tenant_id=tenant_id,
            capabilities=("tenant.operations.read",),
        )
    )
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


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
        await conn.execute(
            text(
                """
                CREATE TRIGGER crisis_events_append_only_update
                BEFORE UPDATE ON crisis_events
                BEGIN
                    SELECT RAISE(ABORT, 'crisis_events is append-only');
                END
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TRIGGER crisis_events_append_only_delete
                BEFORE DELETE ON crisis_events
                BEGIN
                    SELECT RAISE(ABORT, 'crisis_events is append-only');
                END
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

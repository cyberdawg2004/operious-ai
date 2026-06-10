"""Queue operations router tests."""

from __future__ import annotations

import asyncio
import ast
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import Thread
from typing import Any

from fastapi import Depends
import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.dependencies.authority import (
    require_operator_authority,
    require_tenant_observability_read,
)
from app.identity import AuthorityContext
from app.main import create_app
from app.dependencies.database import get_db_session
from app.dependencies.services import get_queue_operations_service
from app.core.queue_depth import QueueDepthBackend, QueueDepthSample
from app.queues import (
    ALL_QUEUES,
    QUEUE_DIAGNOSTIC_NORMAL,
    QUEUE_QA,
)
from app.runtime.db.models import DeadLetterTaskRow
from app.services.queue_operations_service import (
    DEAD_LETTER_REPLAY_CLAIMED,
    DEAD_LETTER_REPLAY_FAILED,
    DEAD_LETTER_REPLAY_NONE,
    DEAD_LETTER_REPLAY_PUBLISHED,
    QueueOperationsService,
)
from app.tenant.db.models import TenantRow
from tests.conftest import requires_postgres, set_pg_rls_tenant

pytestmark = [requires_postgres]

_NOW = datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc)
_TENANT = f"tenant-acme-{uuid.uuid4()}"
_OTHER_TENANT = f"tenant-other-{uuid.uuid4()}"


@pytest.fixture
def pg_tenant_id() -> str:
    return _TENANT


@pytest_asyncio.fixture
async def queue_client(
    pg_session: AsyncSession,
) -> AsyncIterator[tuple[httpx.AsyncClient, Any]]:
    app = create_app()

    async def _db_override() -> AsyncIterator[AsyncSession]:
        yield pg_session

    app.dependency_overrides[get_db_session] = _db_override
    app.dependency_overrides[require_operator_authority] = (
        _operator_authority_override
    )
    app.dependency_overrides[require_tenant_observability_read] = (
        _observability_authority_override
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        yield client, app


@pytest.mark.asyncio
async def test_queue_status_returns_all_queues(
    queue_client: tuple[httpx.AsyncClient, Any],
    pg_session: AsyncSession,
) -> None:
    client, app = queue_client
    redis = _QueueRedis(depth=7, oldest_age_seconds=12.5)
    app.dependency_overrides[get_queue_operations_service] = _service_override(
        QueueOperationsService(
            session=pg_session,
            redis_provider=lambda: redis,  # type: ignore[arg-type]
        )
    )

    response = await client.get(
        "/api/v1/operations/queue-status",
        headers=_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body["queues"]) == set(ALL_QUEUES)
    assert len(body["queues"]) == len(ALL_QUEUES)
    assert body["queues"][QUEUE_DIAGNOSTIC_NORMAL]["depth"] == 7
    assert body["queues"][QUEUE_DIAGNOSTIC_NORMAL]["status"] == "ok"


@pytest.mark.asyncio
async def test_queue_status_ignores_stale_age_when_depth_is_zero(
    queue_client: tuple[httpx.AsyncClient, Any],
    pg_session: AsyncSession,
) -> None:
    client, app = queue_client
    redis = _QueueRedis(depth=0, oldest_age_seconds=9999.0)
    app.dependency_overrides[get_queue_operations_service] = _service_override(
        QueueOperationsService(
            session=pg_session,
            redis_provider=lambda: redis,  # type: ignore[arg-type]
        )
    )

    response = await client.get(
        "/api/v1/operations/queue-status",
        headers=_headers(),
    )

    assert response.status_code == 200
    queue = response.json()["queues"][QUEUE_DIAGNOSTIC_NORMAL]
    assert queue["depth"] == 0
    assert queue["oldest_age_seconds"] is None
    assert queue["status"] == "ok"
    assert redis.zrange_calls == []
    assert (f"queue:age:{QUEUE_DIAGNOSTIC_NORMAL}", "-inf") in {
        (call[0], call[1]) for call in redis.cleanup_calls
    }
    assert redis.zsets[f"queue:age:{QUEUE_DIAGNOSTIC_NORMAL}"] == {}


@pytest.mark.asyncio
async def test_queue_status_age_thresholds_apply_when_depth_is_positive(
    pg_session: AsyncSession,
) -> None:
    settings = _queue_status_settings()

    fresh = await _queue_status_for_age(
        pg_session,
        depth=1,
        oldest_age_seconds=10.0,
        settings=settings,
    )
    warning = await _queue_status_for_age(
        pg_session,
        depth=1,
        oldest_age_seconds=40.0,
        settings=settings,
    )
    critical = await _queue_status_for_age(
        pg_session,
        depth=1,
        oldest_age_seconds=80.0,
        settings=settings,
    )

    assert fresh.status == "ok"
    assert warning.status == "warn"
    assert critical.status == "critical"


@pytest.mark.asyncio
async def test_rabbitmq_zero_depth_ignores_stale_redis_age(
    pg_session: AsyncSession,
) -> None:
    redis = _QueueRedis(depth=0, oldest_age_seconds=9999.0)
    service = QueueOperationsService(
        session=pg_session,
        redis_provider=lambda: redis,  # type: ignore[arg-type]
        queue_depth_provider=_StaticQueueDepthProvider(
            backend="rabbitmq",
            default_depth=0,
        ),
        settings=_queue_status_settings(),
    )

    record = await service.get_queue_status()
    queue = record.queues[QUEUE_DIAGNOSTIC_NORMAL]

    assert queue.depth == 0
    assert queue.oldest_age_seconds is None
    assert queue.status == "ok"
    assert redis.zrange_calls == []
    assert redis.zsets[f"queue:age:{QUEUE_DIAGNOSTIC_NORMAL}"] == {}
    assert redis.zsets["unrelated:key"] == {"do-not-delete": 1.0}


@pytest.mark.asyncio
async def test_rabbitmq_positive_depth_still_applies_valid_age(
    pg_session: AsyncSession,
) -> None:
    service = QueueOperationsService(
        session=pg_session,
        redis_provider=lambda: _QueueRedis(depth=0, oldest_age_seconds=80.0),  # type: ignore[arg-type]
        queue_depth_provider=_StaticQueueDepthProvider(
            backend="rabbitmq",
            default_depth=3,
        ),
        settings=_queue_status_settings(),
    )

    record = await service.get_queue_status()
    queue = record.queues[QUEUE_DIAGNOSTIC_NORMAL]

    assert queue.depth == 3
    assert queue.oldest_age_seconds is not None
    assert queue.oldest_age_seconds >= 79.0
    assert queue.status == "critical"


@pytest.mark.asyncio
async def test_queue_status_returns_unknown_when_redis_down(
    queue_client: tuple[httpx.AsyncClient, Any],
    pg_session: AsyncSession,
) -> None:
    client, app = queue_client
    app.dependency_overrides[get_queue_operations_service] = _service_override(
        QueueOperationsService(
            session=pg_session,
            redis_provider=lambda: _DownRedis(),  # type: ignore[arg-type]
        )
    )

    response = await client.get(
        "/api/v1/operations/queue-status",
        headers=_headers(),
    )

    assert response.status_code == 200
    queues = response.json()["queues"]
    assert set(queues) == set(ALL_QUEUES)
    assert all(item["status"] == "unknown" for item in queues.values())
    assert all(item["error"] == "redis_unavailable" for item in queues.values())


@pytest.mark.asyncio
async def test_queue_status_requires_auth(
    queue_client: tuple[httpx.AsyncClient, Any],
) -> None:
    client, _app = queue_client

    response = await client.get("/api/v1/operations/queue-status")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_dead_letters_returns_tenant_records(
    queue_client: tuple[httpx.AsyncClient, Any],
    pg_session: AsyncSession,
) -> None:
    client, _app = queue_client
    await _seed_dlq(pg_session, tenant_id=_TENANT, seed="own")

    response = await client.get(
        "/api/v1/operations/dead-letters",
        headers=_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["tenant_id"] == _TENANT
    assert body["items"][0]["queue"] == QUEUE_DIAGNOSTIC_NORMAL


@pytest.mark.asyncio
async def test_list_dead_letters_respects_rls(
    queue_client: tuple[httpx.AsyncClient, Any],
    pg_session: AsyncSession,
    pg_seed_session: AsyncSession,
) -> None:
    client, _app = queue_client
    await _seed_dlq(pg_seed_session, tenant_id=_OTHER_TENANT, seed="other")
    await set_pg_rls_tenant(pg_session, _TENANT)

    response = await client.get(
        "/api/v1/operations/dead-letters",
        headers=_headers(),
    )

    assert response.status_code == 200
    assert response.json()["total"] == 0


@pytest.mark.asyncio
async def test_list_dead_letters_filters_by_queue(
    queue_client: tuple[httpx.AsyncClient, Any],
    pg_session: AsyncSession,
) -> None:
    client, _app = queue_client
    await _seed_dlq(pg_session, tenant_id=_TENANT, seed="normal")
    await _seed_dlq(
        pg_session,
        tenant_id=_TENANT,
        seed="qa",
        task_name="score_supervisor_inspection",
        queue=QUEUE_QA,
        metadata={
            "error_class": "QAError",
            "error_message": "qa failed",
            "task_payload": {"inspection_id": "inspection-1", "tenant_id": _TENANT},
            "celery_kwargs": {"inspection_id": "inspection-1", "tenant_id": _TENANT},
            "attempt_count": 1,
        },
    )

    response = await client.get(
        "/api/v1/operations/dead-letters",
        headers=_headers(),
        params={"queue": QUEUE_QA},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["task_name"] == "score_supervisor_inspection"


@pytest.mark.asyncio
async def test_list_dead_letters_filters_by_error_class(
    queue_client: tuple[httpx.AsyncClient, Any],
    pg_session: AsyncSession,
) -> None:
    client, _app = queue_client
    await _seed_dlq(pg_session, tenant_id=_TENANT, seed="one")
    await _seed_dlq(
        pg_session,
        tenant_id=_TENANT,
        seed="two",
        metadata=_metadata(error_class="SpecificError"),
    )

    response = await client.get(
        "/api/v1/operations/dead-letters",
        headers=_headers(),
        params={"error_class": "SpecificError"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["error_class"] == "SpecificError"


@pytest.mark.asyncio
async def test_list_dead_letters_paginates(
    queue_client: tuple[httpx.AsyncClient, Any],
    pg_session: AsyncSession,
) -> None:
    client, _app = queue_client
    await _seed_dlq(pg_session, tenant_id=_TENANT, seed="one", created_at=_at(1))
    await _seed_dlq(pg_session, tenant_id=_TENANT, seed="two", created_at=_at(2))
    await _seed_dlq(pg_session, tenant_id=_TENANT, seed="three", created_at=_at(3))

    response = await client.get(
        "/api/v1/operations/dead-letters",
        headers=_headers(),
        params={"limit": 1, "offset": 1},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["limit"] == 1
    assert body["offset"] == 1
    assert len(body["items"]) == 1


@pytest.mark.asyncio
async def test_list_dead_letters_requires_auth(
    queue_client: tuple[httpx.AsyncClient, Any],
) -> None:
    client, _app = queue_client

    response = await client.get("/api/v1/operations/dead-letters")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_dead_letters_requires_operator_authority(
    pg_session: AsyncSession,
) -> None:
    app = create_app()

    async def _db_override() -> AsyncIterator[AsyncSession]:
        yield pg_session

    app.dependency_overrides[get_db_session] = _db_override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/api/v1/operations/dead-letters",
            headers=_headers(),
        )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_replay_marks_record_as_replayed(
    queue_client: tuple[httpx.AsyncClient, Any],
    pg_session: AsyncSession,
) -> None:
    client, app = queue_client
    row = await _seed_dlq(pg_session, tenant_id=_TENANT, seed="replay")
    sent = _SentTasks()
    app.dependency_overrides[get_queue_operations_service] = _service_override(
        QueueOperationsService(
            session=pg_session,
            replay_publisher=sent,
        )
    )

    response = await client.post(
        f"/api/v1/operations/dead-letters/{row.dead_letter_task_id}/replay",
        headers=_headers(),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "replayed"
    assert sent.calls == [
        (
            "execute_diagnostic_agent",
            {"execution_id": "execution-replay", "tenant_id": _TENANT},
            QUEUE_DIAGNOSTIC_NORMAL,
        )
    ]
    await pg_session.refresh(row)
    assert row.replayed is True
    assert row.replay_state == DEAD_LETTER_REPLAY_PUBLISHED
    assert row.replay_claim_id is not None
    assert row.replayed_by == "operator-principal"
    assert row.replayed_at is not None


@pytest.mark.asyncio
async def test_replay_commits_claimed_state_before_publish(
    pg_engine: AsyncEngine,
) -> None:
    seed = f"claimed-first-{uuid.uuid4()}"
    async with _queue_session_for_tenant(pg_engine, _TENANT) as session:
        row = await _seed_dlq(
            session,
            tenant_id=_TENANT,
            seed=seed,
        )
        dlq_id = row.dead_letter_task_id
        await session.commit()

    sent = _InspectingSentTasks(
        engine=pg_engine,
        dlq_id=dlq_id,
        tenant_id=_TENANT,
    )
    async with _queue_session_for_tenant(pg_engine, _TENANT) as session:
        service = QueueOperationsService(session=session, replay_publisher=sent)

        result = await service.replay_dead_letter(
            dlq_id=str(dlq_id),
            tenant_id=_TENANT,
            replayed_by="operator-principal",
        )

    assert result.status == "replayed"
    assert sent.observed_state == DEAD_LETTER_REPLAY_CLAIMED
    assert sent.observed_replayed is False
    assert sent.calls == [
        (
            "execute_diagnostic_agent",
            {"execution_id": f"execution-{seed}", "tenant_id": _TENANT},
            QUEUE_DIAGNOSTIC_NORMAL,
        )
    ]


@pytest.mark.asyncio
async def test_replay_publish_failure_marks_failed_not_stranded(
    pg_session: AsyncSession,
) -> None:
    row = await _seed_dlq(pg_session, tenant_id=_TENANT, seed="publish-fails")
    service = QueueOperationsService(
        session=pg_session,
        replay_publisher=_FailingSentTasks(),
    )

    with pytest.raises(RuntimeError, match="broker unavailable"):
        await service.replay_dead_letter(
            dlq_id=str(row.dead_letter_task_id),
            tenant_id=_TENANT,
            replayed_by="operator-principal",
        )

    await pg_session.refresh(row)
    assert row.replay_state == DEAD_LETTER_REPLAY_FAILED
    assert row.replayed is False
    assert row.replay_claim_id is not None
    assert row.replay_last_error is not None
    assert "RuntimeError: broker unavailable" in row.replay_last_error


@pytest.mark.asyncio
async def test_replay_recovery_reattempts_failed_row(
    pg_session: AsyncSession,
) -> None:
    old_claim = uuid.uuid5(uuid.NAMESPACE_URL, "failed-replay-claim")
    row = await _seed_dlq(
        pg_session,
        tenant_id=_TENANT,
        seed="failed-retry",
        replay_state=DEAD_LETTER_REPLAY_FAILED,
        replay_attempt_count=1,
        replay_claim_id=old_claim,
        replay_claimed_at=_NOW,
    )
    sent = _SentTasks()
    service = QueueOperationsService(session=pg_session, replay_publisher=sent)

    recovered = await service.recover_dead_letter_replays(
        claimed_before_or_at=_NOW,
        tenant_id=_TENANT,
    )
    await pg_session.commit()
    await service.replay_dead_letter(
        dlq_id=str(row.dead_letter_task_id),
        tenant_id=_TENANT,
        replayed_by="operator-principal",
    )

    await pg_session.refresh(row)
    assert recovered.recovered_count == 1
    assert recovered.recovered_ids == (str(row.dead_letter_task_id),)
    assert row.replay_state == DEAD_LETTER_REPLAY_PUBLISHED
    assert row.replayed is True
    assert row.replay_attempt_count == 2
    assert row.replay_claim_id != old_claim
    assert sent.calls == [
        (
            "execute_diagnostic_agent",
            {"execution_id": "execution-failed-retry", "tenant_id": _TENANT},
            QUEUE_DIAGNOSTIC_NORMAL,
        )
    ]


@pytest.mark.asyncio
async def test_replay_returns_404_for_missing(
    queue_client: tuple[httpx.AsyncClient, Any],
) -> None:
    client, _app = queue_client

    response = await client.post(
        f"/api/v1/operations/dead-letters/{uuid.uuid4()}/replay",
        headers=_headers(),
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_replay_returns_404_for_wrong_tenant(
    queue_client: tuple[httpx.AsyncClient, Any],
    pg_session: AsyncSession,
    pg_seed_session: AsyncSession,
) -> None:
    client, _app = queue_client
    row = await _seed_dlq(
        pg_seed_session,
        tenant_id=_OTHER_TENANT,
        seed="wrong",
    )
    await set_pg_rls_tenant(pg_session, _TENANT)

    response = await client.post(
        f"/api/v1/operations/dead-letters/{row.dead_letter_task_id}/replay",
        headers=_headers(),
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_replay_returns_409_if_already_replayed(
    queue_client: tuple[httpx.AsyncClient, Any],
    pg_session: AsyncSession,
) -> None:
    client, _app = queue_client
    row = await _seed_dlq(
        pg_session,
        tenant_id=_TENANT,
        seed="already",
        replayed=True,
    )

    response = await client.post(
        f"/api/v1/operations/dead-letters/{row.dead_letter_task_id}/replay",
        headers=_headers(),
    )

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_concurrent_replay_returns_409_for_second_caller(
    pg_engine: AsyncEngine,
    pg_seed_engine: AsyncEngine | None,
) -> None:
    if pg_seed_engine is None:
        pytest.skip("requires owner seed engine for committed DLQ fixture")

    seed = f"concurrent-{uuid.uuid4()}"
    async with pg_seed_engine.begin() as connection:
        seed_session = AsyncSession(bind=connection, expire_on_commit=False)
        try:
            row = await _seed_dlq(
                seed_session,
                tenant_id=_TENANT,
                seed=seed,
            )
            dlq_id = row.dead_letter_task_id
        finally:
            await seed_session.close()

    app = create_app()
    sent = _SentTasks()

    async def _db_override() -> AsyncIterator[AsyncSession]:
        connection = await pg_engine.connect()
        transaction = await connection.begin()
        await connection.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": _TENANT},
        )
        session = AsyncSession(bind=connection, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()
            if transaction.is_active:
                await transaction.rollback()
            await connection.close()

    async def _service_override_for_request(
        session: AsyncSession = Depends(get_db_session),
    ) -> QueueOperationsService:
        return QueueOperationsService(session=session, replay_publisher=sent)

    app.dependency_overrides[get_db_session] = _db_override
    app.dependency_overrides[require_operator_authority] = (
        _operator_authority_override
    )
    app.dependency_overrides[get_queue_operations_service] = (
        _service_override_for_request
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        responses = await asyncio.gather(
            client.post(
                f"/api/v1/operations/dead-letters/{dlq_id}/replay",
                headers=_headers(),
            ),
            client.post(
                f"/api/v1/operations/dead-letters/{dlq_id}/replay",
                headers=_headers(),
            ),
        )

    assert sorted(response.status_code for response in responses) == [200, 409]
    assert sent.calls == [
        (
            "execute_diagnostic_agent",
            {"execution_id": f"execution-{seed}", "tenant_id": _TENANT},
            QUEUE_DIAGNOSTIC_NORMAL,
        )
    ]


@pytest.mark.asyncio
async def test_replay_requires_auth(
    queue_client: tuple[httpx.AsyncClient, Any],
) -> None:
    client, _app = queue_client

    response = await client.post(
        f"/api/v1/operations/dead-letters/{uuid.uuid4()}/replay",
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_replay_requires_operator_authority(
    pg_session: AsyncSession,
) -> None:
    app = create_app()

    async def _db_override() -> AsyncIterator[AsyncSession]:
        yield pg_session

    app.dependency_overrides[get_db_session] = _db_override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.post(
            f"/api/v1/operations/dead-letters/{uuid.uuid4()}/replay",
            headers=_headers(),
        )

    assert response.status_code == 403


def test_queue_operations_router_uses_service_boundary() -> None:
    router_path = (
        Path(__file__).parent.parent
        / "app"
        / "api"
        / "v1"
        / "routers"
        / "queue_operations.py"
    )
    tree = ast.parse(router_path.read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    text = router_path.read_text(encoding="utf-8")

    assert "app.runtime.db.models" not in imported_modules
    assert "app.core.redis" not in imported_modules
    assert "DeadLetterTaskRow" not in text
    assert "get_redis_client" not in text
    assert "get_queue_operations_service" in text


def _headers(tenant: str = _TENANT) -> dict[str, str]:
    return {"X-Tenant-ID": tenant, "X-Principal-ID": "principal-test"}


async def _operator_authority_override() -> AuthorityContext:
    return AuthorityContext.from_raw(
        tenant_id=_TENANT,
        principal_id="operator-principal",
        capabilities=frozenset({"operator"}),
    )


async def _observability_authority_override() -> AuthorityContext:
    return AuthorityContext.from_raw(
        tenant_id=_TENANT,
        principal_id="observer-principal",
        capabilities=frozenset({"tenant.observability.read"}),
    )


def _service_override(
    service: QueueOperationsService,
) -> Callable[[], Awaitable[QueueOperationsService]]:
    async def override() -> QueueOperationsService:
        return service

    return override


async def _seed_dlq(
    session: AsyncSession,
    *,
    tenant_id: str,
    seed: str,
    task_name: str = "execute_diagnostic_agent",
    queue: str | None = QUEUE_DIAGNOSTIC_NORMAL,
    metadata: Mapping[str, Any] | None = None,
    replayed: bool = False,
    replay_state: str | None = None,
    replay_attempt_count: int = 0,
    replay_claim_id: uuid.UUID | None = None,
    replay_claimed_at: datetime | None = None,
    created_at: datetime | None = None,
) -> DeadLetterTaskRow:
    await session.merge(TenantRow(tenant_id=tenant_id))
    await session.flush()
    row = DeadLetterTaskRow(
        dead_letter_task_id=uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"queue-operations-dlq:{tenant_id}:{seed}",
        ),
        tenant_id=tenant_id,
        task_name=task_name,
        task_id=f"task-{seed}",
        execution_id=None,
        queue=queue,
        reason="retry budget exhausted",
        retry_count=3,
        created_at=created_at or _NOW,
        replayed=replayed,
        replay_state=(
            replay_state
            if replay_state is not None
            else (
                DEAD_LETTER_REPLAY_PUBLISHED
                if replayed
                else DEAD_LETTER_REPLAY_NONE
            )
        ),
        replay_claim_id=replay_claim_id,
        replay_attempt_count=replay_attempt_count,
        replay_claimed_at=replay_claimed_at,
        replayed_at=_NOW if replayed else None,
        replayed_by="operator-principal" if replayed else None,
        metadata_json=dict(
            metadata or _metadata(seed=seed, tenant_id=tenant_id)
        ),
    )
    session.add(row)
    await session.flush()
    return row


def _metadata(
    *,
    seed: str = "default",
    tenant_id: str = _TENANT,
    error_class: str = "ProviderError",
) -> dict[str, Any]:
    execution_id = f"execution-{seed}"
    return {
        "execution_id": execution_id,
        "session_id": f"session-{seed}",
        "tenant_id": tenant_id,
        "attempt_count": 3,
        "attempt_id": f"attempt-{seed}",
        "dispatch_id": f"dispatch-{seed}",
        "error_type": error_class,
        "error_class": error_class,
        "error_message": f"{error_class} happened",
        "last_traceback": "traceback",
        "attempt_number": 3,
        "task_payload": {
            "execution_id": execution_id,
            "attempt_id": f"attempt-{seed}",
            "attempt_number": 3,
            "dispatch_id": f"dispatch-{seed}",
            "session_id": f"session-{seed}",
            "tenant_id": tenant_id,
        },
        "celery_kwargs": {
            "execution_id": execution_id,
            "tenant_id": tenant_id,
        },
    }


def _at(second: int) -> datetime:
    return datetime(2026, 5, 25, 12, 0, second, tzinfo=timezone.utc)


async def _queue_status_for_age(
    pg_session: AsyncSession,
    *,
    depth: int,
    oldest_age_seconds: float,
    settings: Any,
):
    service = QueueOperationsService(
        session=pg_session,
        redis_provider=lambda: _QueueRedis(  # type: ignore[arg-type]
            depth=depth,
            oldest_age_seconds=oldest_age_seconds,
        ),
        settings=settings,
    )
    return (await service.get_queue_status()).queues[QUEUE_DIAGNOSTIC_NORMAL]


def _queue_status_settings() -> Any:
    from app.core.config import get_settings

    return get_settings().model_copy(
        update={
            "ADMISSION_QUEUE_AGE_WARN_SECONDS": 30,
            "ADMISSION_QUEUE_AGE_REJECT_SECONDS": 60,
            "ADMISSION_QUEUE_DEPTH_WARN": 500,
            "ADMISSION_QUEUE_DEPTH_REJECT": 2000,
        }
    )


class _QueueRedis:
    def __init__(
        self,
        *,
        depth: int,
        oldest_age_seconds: float | None = None,
    ) -> None:
        self.depth = depth
        self.oldest_age_seconds = oldest_age_seconds
        self.zrange_calls: list[str] = []
        self.cleanup_calls: list[tuple[str, float | str, float | str]] = []
        self.zsets: dict[str, dict[str, float]] = {
            f"queue:age:{QUEUE_DIAGNOSTIC_NORMAL}": {"stale-member": 1.0},
            "unrelated:key": {"do-not-delete": 1.0}
        }

    async def llen(self, _name: str) -> int:
        return self.depth

    async def zrange(
        self,
        _name: str,
        _start: int,
        _end: int,
        *,
        withscores: bool = False,
    ) -> list[tuple[str, float]]:
        assert withscores is True
        self.zrange_calls.append(_name)
        if self.oldest_age_seconds is None:
            return []
        return [("member", datetime.now().timestamp() - self.oldest_age_seconds)]

    async def zremrangebyscore(
        self,
        name: str,
        min_score: float | str,
        max_score: float | str,
    ) -> int:
        self.cleanup_calls.append((name, min_score, max_score))
        members = self.zsets.get(name)
        if members is None:
            return 0
        before = len(members)
        upper = float(max_score)
        self.zsets[name] = {
            member: score
            for member, score in members.items()
            if score > upper
        }
        return before - len(self.zsets[name])


class _DownRedis:
    async def llen(self, _name: str) -> int:
        raise ConnectionError("redis down")


class _StaticQueueDepthProvider:
    def __init__(
        self,
        *,
        backend: QueueDepthBackend = "redis",
        default_depth: int = 0,
    ) -> None:
        self.backend: QueueDepthBackend = backend
        self.default_depth = default_depth

    async def get_queue_depth(self, queue_name: str) -> QueueDepthSample:
        return QueueDepthSample(
            queue_name=queue_name,
            depth=self.default_depth,
            messages_ready=self.default_depth,
            messages_unacknowledged=0,
            messages=self.default_depth,
        )


class _SentTasks:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], str]] = []

    def publish(
        self,
        *,
        task_name: str,
        kwargs: Mapping[str, Any],
        queue: str,
    ) -> None:
        self.calls.append((task_name, dict(kwargs), queue))


class _FailingSentTasks:
    def publish(
        self,
        *,
        task_name: str,
        kwargs: Mapping[str, Any],
        queue: str,
    ) -> None:
        del task_name, kwargs, queue
        raise RuntimeError("broker unavailable")


class _InspectingSentTasks(_SentTasks):
    def __init__(
        self,
        *,
        engine: AsyncEngine,
        dlq_id: uuid.UUID,
        tenant_id: str,
    ) -> None:
        super().__init__()
        self._engine = engine
        self._dlq_id = dlq_id
        self._tenant_id = tenant_id
        self.observed_state: str | None = None
        self.observed_replayed: bool | None = None

    def publish(
        self,
        *,
        task_name: str,
        kwargs: Mapping[str, Any],
        queue: str,
    ) -> None:
        errors: list[BaseException] = []

        def runner() -> None:
            try:
                asyncio.run(self._inspect_claim())
            except BaseException as exc:  # noqa: BLE001 - test helper surfaces it.
                errors.append(exc)

        thread = Thread(target=runner)
        thread.start()
        thread.join()
        if errors:
            raise errors[0]
        super().publish(task_name=task_name, kwargs=kwargs, queue=queue)

    async def _inspect_claim(self) -> None:
        async with self._engine.connect() as connection:
            await connection.execute(
                text("SELECT set_config('app.current_tenant_id', :t, false)"),
                {"t": self._tenant_id},
            )
            row = (
                await connection.execute(
                    text(
                        "SELECT replay_state, replayed "
                        "FROM dead_letter_tasks "
                        "WHERE dead_letter_task_id = :id "
                        "AND tenant_id = :tenant_id"
                    ),
                    {
                        "id": self._dlq_id,
                        "tenant_id": self._tenant_id,
                    },
                )
            ).one()
            self.observed_state = str(row[0])
            self.observed_replayed = bool(row[1])


@asynccontextmanager
async def _queue_session_for_tenant(
    engine: AsyncEngine,
    tenant_id: str,
) -> AsyncIterator[AsyncSession]:
    connection = await engine.connect()
    await connection.execute(
        text("SELECT set_config('app.current_tenant_id', :t, false)"),
        {"t": tenant_id},
    )
    await connection.commit()
    session = AsyncSession(bind=connection, expire_on_commit=False)
    try:
        yield session
    finally:
        await session.close()
        if connection.in_transaction():
            await connection.rollback()
        await connection.close()

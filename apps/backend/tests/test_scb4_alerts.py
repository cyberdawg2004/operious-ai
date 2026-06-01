"""PR_SCB4 semantic circuit alert and read-surface coverage."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.dependencies.database import get_db_session
from app.execution.db.models import ExecutionRow
from app.hardening.observability.alert_evaluator import AlertEvaluator
from app.main import create_app
from app.queues import QUEUE_DIAGNOSTIC_NORMAL
from app.runtime.db.models import DeadLetterTaskRow, ProviderCircuitStateRow
from app.runtime.provider_circuit_breaker import ProviderCircuitState
from app.semantic import SemanticCircuitEventRecord, SemanticCircuitEventRepository
from app.semantic.db.models import SemanticCircuitEventRow
from tests.conftest import requires_postgres, set_pg_rls_tenant


@requires_postgres
@pytest.mark.asyncio
async def test_alert_condition_fires_on_tripped_circuit(
    pg_session: AsyncSession,
    pg_tenant_id: str,
) -> None:
    await _seed_event(
        pg_session,
        tenant_id=pg_tenant_id,
        channel="email",
        state="TRIPPED",
        occurred_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        cluster_size=7,
    )

    results = await _evaluator(
        owner_session=pg_session,
    )._check_semantic_circuit_tripped(pg_session)

    assert len(results) == 1
    assert results[0].condition_name == "semantic_circuit_tripped"
    assert results[0].severity == "warning"
    assert results[0].metadata["tenant_id"] == pg_tenant_id
    assert results[0].metadata["channel"] == "email"


@requires_postgres
@pytest.mark.asyncio
async def test_alert_condition_silent_when_no_recent_trips(
    pg_session: AsyncSession,
    pg_tenant_id: str,
) -> None:
    await _seed_event(
        pg_session,
        tenant_id=pg_tenant_id,
        channel="email",
        state="TRIPPED",
        occurred_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        cluster_size=4,
    )

    results = await _evaluator(
        owner_session=pg_session,
    )._check_semantic_circuit_tripped(pg_session)

    assert results == []


@pytest.mark.asyncio
async def test_alert_condition_fail_open_on_db_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evaluator = _evaluator(owner_session=_FailingSession())

    async def no_results() -> list[Any]:
        return []

    async def no_results_with_session(_session: Any) -> list[Any]:
        return []

    assert await evaluator._check_semantic_circuit_tripped(None) == []  # type: ignore[arg-type]

    monkeypatch.setattr(evaluator, "_check_dlq_spike", no_results_with_session)
    monkeypatch.setattr(evaluator, "_check_provider_circuits", no_results_with_session)
    monkeypatch.setattr(evaluator, "_check_replay_mismatch", no_results_with_session)
    monkeypatch.setattr(evaluator, "_check_db_pool", no_results)
    assert await evaluator.evaluate_all(None) == []  # type: ignore[arg-type]


@requires_postgres
@pytest.mark.asyncio
async def test_circuit_states_api_returns_latest_per_channel(
    pg_session: AsyncSession,
    pg_tenant_id: str,
) -> None:
    client = await _semantic_client(pg_session)
    channel = f"email-{uuid.uuid4()}"
    now = datetime.now(timezone.utc)
    await _seed_event(
        pg_session,
        tenant_id=pg_tenant_id,
        channel=channel,
        state="CLOSED",
        occurred_at=now - timedelta(minutes=2),
        cluster_size=1,
    )
    await _seed_event(
        pg_session,
        tenant_id=pg_tenant_id,
        channel=channel,
        state="TRIPPED",
        occurred_at=now - timedelta(minutes=1),
        cluster_size=6,
    )

    async with client as http_client:
        response = await http_client.get(
            "/api/v1/semantic/circuit-states",
            headers=_headers(pg_tenant_id),
        )

    assert response.status_code == 200
    states = [
        item for item in response.json() if item["channel"] == channel
    ]
    assert len(states) == 1
    assert states[0]["state"] == "TRIPPED"
    assert states[0]["cluster_size"] == 6


@requires_postgres
@pytest.mark.asyncio
async def test_circuit_states_tenant_isolation(
    pg_session: AsyncSession,
) -> None:
    tenant_a = f"tenant-a-{uuid.uuid4()}"
    tenant_b = f"tenant-b-{uuid.uuid4()}"
    await set_pg_rls_tenant(pg_session, tenant_a)
    await _seed_event(
        pg_session,
        tenant_id=tenant_a,
        channel="whatsapp",
        state="TRIPPED",
        occurred_at=datetime.now(timezone.utc),
        cluster_size=5,
    )
    await set_pg_rls_tenant(pg_session, tenant_b)
    client = await _semantic_client(pg_session)

    async with client as http_client:
        response = await http_client.get(
            "/api/v1/semantic/circuit-states",
            headers=_headers(tenant_b),
        )

    assert response.status_code == 200
    assert response.json() == []


async def _seed_event(
    session: AsyncSession,
    *,
    tenant_id: str,
    channel: str,
    state: str,
    occurred_at: datetime,
    cluster_size: int,
) -> None:
    await SemanticCircuitEventRepository(session).write(
        SemanticCircuitEventRecord(
            event_id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            channel=channel,
            state=state,
            trigger_ticket_id=None,
            cluster_size=cluster_size,
            similarity_threshold=0.7,
            window_seconds=300,
            occurred_at=occurred_at,
            metadata={"seed": "scb4"},
        )
    )
    await session.flush()


async def _semantic_client(pg_session: AsyncSession) -> httpx.AsyncClient:
    app = create_app()

    async def _db_override() -> AsyncIterator[AsyncSession]:
        yield pg_session

    app.dependency_overrides[get_db_session] = _db_override
    # Spec 1a-ext: semantic circuit-state reads are gated on
    # tenant.observability.read. The legacy-header auth this test uses carries
    # no capabilities, so grant the read capability explicitly.
    from app.dependencies.authority import require_tenant_observability_read
    from app.identity import AuthorityContext

    app.dependency_overrides[require_tenant_observability_read] = lambda: AuthorityContext(
        capabilities=("tenant.observability.read",)
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    )


def _headers(tenant_id: str) -> dict[str, str]:
    return {"X-Tenant-ID": tenant_id, "X-Principal-ID": "principal-scb4"}


def _evaluator(
    *,
    owner_session: Any,
) -> AlertEvaluator:
    return AlertEvaluator(
        settings=Settings(DATABASE_URL="sqlite+aiosqlite:///:memory:"),
        redis_provider=lambda: _RedisFake(),
        admission_gate_factory=lambda: _AdmissionGateFake(),
        owner_session_context_factory=lambda: _OwnerSessionContext(owner_session),
        engine_provider=lambda: _EngineFake(),
        queue_names=(QUEUE_DIAGNOSTIC_NORMAL,),
        dead_letter_task_row=DeadLetterTaskRow,
        provider_circuit_state_row=ProviderCircuitStateRow,
        semantic_circuit_event_row=SemanticCircuitEventRow,
        execution_row=ExecutionRow,
        provider_open_state=ProviderCircuitState.OPEN.value,
    )


class _AdmissionGateFake:
    async def queue_age_seconds(self, *, queue_name: str) -> float | None:
        del queue_name
        return None

    async def redis_memory_pct(self) -> float | None:
        return None


class _RedisFake:
    async def exists(self, key: str) -> int:
        del key
        return 0

    async def set(
        self,
        key: str,
        value: str,
        *,
        ex: int | None = None,
    ) -> bool:
        del key, value, ex
        return True

    async def get(self, key: str) -> str | None:
        del key
        return None


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


class _FailingSession:
    async def execute(self, statement: object) -> object:
        del statement
        raise RuntimeError("semantic circuit event store unavailable")


class _PoolFake:
    def checkedout(self) -> int:
        return 0

    def size(self) -> int:
        return 10

    def overflow(self) -> int:
        return 0


class _SyncEngineFake:
    pool = _PoolFake()


class _EngineFake:
    sync_engine = _SyncEngineFake()

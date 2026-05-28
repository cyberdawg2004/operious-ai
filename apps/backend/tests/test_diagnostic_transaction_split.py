"""Diagnostic LLM transaction-split regression tests for SAFE-4."""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.cognition.llm import DiagnosticLLMMessage
from app.cognition.models import (
    DiagnosticLLMCompletion,
    DiagnosticLLMUsage,
)
from app.coordination.identity import derive_coordination_id, derive_message_id
from app.coordination.persistence import CoordinationRecord
from app.coordination.persistence.postgres import PostgresCoordinationPersistence
from app.core.config import get_settings
from app.db.tenant_context import get_current_tenant, set_current_tenant
from app.db.url import build_database_engine_config
from app.execution import ExecutionRuntime, ExecutionState
from app.execution.persistence import PostgresExecutionPersistence
from app.knowledge import (
    DeterministicHashEmbeddingProvider,
    DeterministicKnowledgeChunker,
    KnowledgeRuntime,
)
from app.knowledge.persistence import PostgresKnowledgeRepository
from app.session.enums import SessionLifecyclePhase, SessionScope
from app.session.identity import derive_lineage_id, derive_session_id
from app.session.persistence import PostgresSessionPersistence, SessionRecord
from app.tenant.db.models import TenantRow
from app.tenant.enums import (
    TenantKnowledgeDocumentStatus,
    TenantKnowledgeDocumentType,
)
from app.tenant.identity import derive_knowledge_document_id
from app.tenant.persistence import (
    PostgresTenantConfigurationRepository,
    TenantKnowledgeDocumentRecord,
)
from app.workers import agent_tasks
from app.workers.agent_tasks import (
    _DiagnosticExecutionWorkItem,
    _DiagnosticReasoningDraft,
    _complete_diagnostic_reasoning_snapshot,
    _generate_diagnostic_reasoning_for_work_item,
    _load_diagnostic_reasoning_snapshot,
    _persist_diagnostic_success,
    _set_transaction_tenant,
)
from tests.conftest import (
    TEST_DATABASE_URL_ENV,
    database_url_skip_reason,
    execution_admission_token,
    requires_postgres,
)

pytestmark = [requires_postgres]

_NOW = datetime(2026, 5, 29, 12, 0, tzinfo=timezone.utc)


@dataclass(slots=True)
class _ScriptedWorkerLLMClient:
    started: asyncio.Event | None = None
    release: asyncio.Event | None = None
    events: list[str] = field(default_factory=list)
    provider_name: str = "safe4-scripted-provider"
    model_name: str = "safe4-scripted-model"
    calls: int = 0

    async def complete(
        self,
        *,
        system_prompt: str,
        messages: Sequence[DiagnosticLLMMessage],
        max_output_tokens: int,
        temperature: float,
        tenant_id: str | None = None,
    ) -> DiagnosticLLMCompletion:
        del system_prompt, messages, max_output_tokens, temperature, tenant_id
        self.calls += 1
        self.events.append("provider_start")
        if self.started is not None:
            self.started.set()
        if self.release is not None:
            await self.release.wait()
        self.events.append("provider_done")
        return DiagnosticLLMCompletion(
            provider=self.provider_name,
            model=self.model_name,
            text=(
                '{"summary":"Charging replacement diagnosis grounded in SOP.",'
                '"category":"charging_issue","confidence":0.87,'
                '"reasoning":"The charging symptoms and replacement request '
                'match the cited SOP."}'
            ),
            usage=DiagnosticLLMUsage(
                prompt_tokens=42,
                completion_tokens=18,
                total_tokens=60,
            ),
            raw_metadata={"safe4": True},
        )


@dataclass(frozen=True, slots=True)
class _SeededDiagnostic:
    tenant_id: str
    execution_id: str
    session_id: str
    dispatch_id: str
    content: str


@pytest.mark.asyncio
async def test_normal_flow_transaction_split_completes_end_to_end(
    pg_engine: AsyncEngine,
    pg_seed_engine: AsyncEngine | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if pg_seed_engine is None:
        pytest.skip("requires owner seed engine")
    tenant_id = f"tenant-safe4-normal-{uuid.uuid4()}"
    seeded = await _seed_diagnostic(pg_seed_engine, tenant_id=tenant_id)
    session_factory = _session_factory(pg_engine)
    worker_id = "pytest:safe4-normal"
    client = _ScriptedWorkerLLMClient()
    _patch_llm(monkeypatch, client)
    work_item = await _claim_work_item(
        session_factory,
        seeded=seeded,
        worker_id=worker_id,
    )

    draft = await _generate_diagnostic_reasoning_for_work_item(
        session_factory=session_factory,
        work_item=work_item,
        worker_id=worker_id,
    )
    result = await _persist_diagnostic_success(
        session_factory=session_factory,
        work_item=work_item,
        worker_id=worker_id,
        result=draft,
    )

    assert result["status"] == "completed"
    assert client.calls == 1
    async with _tenant_session(pg_engine, tenant_id) as session:
        execution = await ExecutionRuntime(
            persistence=PostgresExecutionPersistence(session)
        ).get_execution(seeded.execution_id)
    assert execution is not None
    assert execution.state is ExecutionState.COMPLETED

    rows = await _forensic_counts(pg_seed_engine, seeded)
    assert rows["usage"] == 1
    assert rows["audit"] == 1
    assert rows["completed_events"] == 1
    citations = rows["retrieved_citations"]
    assert isinstance(citations, list)
    assert citations
    citation = citations[0]
    assert citation["chunk_id"]
    assert citation["vector_id"]
    assert citation["document_version"] == 1
    assert citation["content_excerpt_sha256"]


@pytest.mark.asyncio
async def test_provider_call_does_not_hold_pool_connection(
    pg_seed_engine: AsyncEngine | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if pg_seed_engine is None:
        pytest.skip("requires owner seed engine")
    tenant_id = f"tenant-safe4-pool-{uuid.uuid4()}"
    seeded = await _seed_diagnostic(pg_seed_engine, tenant_id=tenant_id)
    engine = _pooled_test_engine(pool_size=1)
    session_factory = _session_factory(engine)
    worker_id = "pytest:safe4-pool"
    started = asyncio.Event()
    release = asyncio.Event()
    client = _ScriptedWorkerLLMClient(started=started, release=release)
    _patch_llm(monkeypatch, client)
    work_item = await _claim_work_item(
        session_factory,
        seeded=seeded,
        worker_id=worker_id,
    )

    task = asyncio.create_task(
        _generate_diagnostic_reasoning_for_work_item(
            session_factory=session_factory,
            work_item=work_item,
            worker_id=worker_id,
        )
    )
    await asyncio.wait_for(started.wait(), timeout=5)
    async with session_factory() as session:
        await _set_transaction_tenant(session, tenant_id)
        assert (await session.execute(text("SELECT 1"))).scalar_one() == 1
        await session.rollback()
    release.set()
    try:
        await asyncio.wait_for(task, timeout=5)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_claim_lost_preserves_forensics_and_skips_completion(
    pg_engine: AsyncEngine,
    pg_seed_engine: AsyncEngine | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if pg_seed_engine is None:
        pytest.skip("requires owner seed engine")
    tenant_id = f"tenant-safe4-claimlost-{uuid.uuid4()}"
    seeded = await _seed_diagnostic(pg_seed_engine, tenant_id=tenant_id)
    session_factory = _session_factory(pg_engine)
    worker_id = "pytest:safe4-stale"
    started = asyncio.Event()
    release = asyncio.Event()
    client = _ScriptedWorkerLLMClient(started=started, release=release)
    _patch_llm(monkeypatch, client)
    work_item = await _claim_work_item(
        session_factory,
        seeded=seeded,
        worker_id=worker_id,
    )

    task = asyncio.create_task(
        _generate_diagnostic_reasoning_for_work_item(
            session_factory=session_factory,
            work_item=work_item,
            worker_id=worker_id,
        )
    )
    await asyncio.wait_for(started.wait(), timeout=5)
    await _recover_claim(session_factory, seeded.execution_id, tenant_id)
    release.set()
    draft = await asyncio.wait_for(task, timeout=5)
    result = await _persist_diagnostic_success(
        session_factory=session_factory,
        work_item=work_item,
        worker_id=worker_id,
        result=draft,
    )

    assert result["status"] == "claim_lost"
    rows = await _forensic_counts(pg_seed_engine, seeded)
    assert rows["usage"] == 1
    assert rows["audit"] == 1
    assert rows["completed_events"] == 0
    async with _tenant_session(pg_engine, tenant_id) as session:
        execution = await ExecutionRuntime(
            persistence=PostgresExecutionPersistence(session)
        ).get_execution(seeded.execution_id)
    assert execution is not None
    assert execution.state is ExecutionState.REQUESTED


@pytest.mark.asyncio
async def test_retry_idempotency_does_not_double_write(
    pg_engine: AsyncEngine,
    pg_seed_engine: AsyncEngine | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if pg_seed_engine is None:
        pytest.skip("requires owner seed engine")
    tenant_id = f"tenant-safe4-idempotent-{uuid.uuid4()}"
    seeded = await _seed_diagnostic(pg_seed_engine, tenant_id=tenant_id)
    session_factory = _session_factory(pg_engine)
    worker_id = "pytest:safe4-idempotent"
    _patch_llm(monkeypatch, _ScriptedWorkerLLMClient())
    work_item = await _claim_work_item(
        session_factory,
        seeded=seeded,
        worker_id=worker_id,
    )
    draft = await _generate_diagnostic_reasoning_for_work_item(
        session_factory=session_factory,
        work_item=work_item,
        worker_id=worker_id,
    )

    first = await _persist_diagnostic_success(
        session_factory=session_factory,
        work_item=work_item,
        worker_id=worker_id,
        result=draft,
    )
    second = await _persist_diagnostic_success(
        session_factory=session_factory,
        work_item=work_item,
        worker_id=worker_id,
        result=draft,
    )

    assert first["status"] == "completed"
    assert second["status"] == "claim_lost"
    rows = await _forensic_counts(pg_seed_engine, seeded)
    assert rows["usage"] == 1
    assert rows["audit"] == 1
    assert rows["governance"] == 1
    assert rows["completed_events"] == 1


@pytest.mark.asyncio
async def test_transaction_b_cross_tenant_write_is_blocked_by_rls(
    pg_engine: AsyncEngine,
    pg_seed_engine: AsyncEngine | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if pg_seed_engine is None:
        pytest.skip("requires owner seed engine")
    tenant_a = f"tenant-safe4-rls-a-{uuid.uuid4()}"
    tenant_b = f"tenant-safe4-rls-b-{uuid.uuid4()}"
    seeded_a = await _seed_diagnostic(pg_seed_engine, tenant_id=tenant_a)
    seeded_b = await _seed_diagnostic(pg_seed_engine, tenant_id=tenant_b)
    session_factory = _session_factory(pg_engine)
    worker_id = "pytest:safe4-rls"
    _patch_llm(monkeypatch, _ScriptedWorkerLLMClient())
    work_item_a = await _claim_work_item(
        session_factory,
        seeded=seeded_a,
        worker_id=worker_id,
    )
    snapshot_b = await _load_diagnostic_reasoning_snapshot(
        session_factory=session_factory,
        work_item=await _claim_work_item(
            session_factory,
            seeded=seeded_b,
            worker_id="pytest:safe4-rls-b",
        ),
        worker_id="pytest:safe4-rls-b",
    )
    completion_b = await _complete_diagnostic_reasoning_snapshot(snapshot_b)

    with pytest.raises(Exception):
        await _persist_diagnostic_success(
            session_factory=session_factory,
            work_item=work_item_a,
            worker_id=worker_id,
            result=_DiagnosticReasoningDraft(
                snapshot=snapshot_b,
                completion=completion_b,
            ),
        )

    rows = await _forensic_counts(pg_seed_engine, seeded_b)
    assert rows["usage"] == 0
    assert rows["audit"] == 0


@pytest.mark.asyncio
async def test_circuit_write_happens_after_provider_before_transaction_b(
    pg_engine: AsyncEngine,
    pg_seed_engine: AsyncEngine | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if pg_seed_engine is None:
        pytest.skip("requires owner seed engine")
    tenant_id = f"tenant-safe4-circuit-{uuid.uuid4()}"
    seeded = await _seed_diagnostic(pg_seed_engine, tenant_id=tenant_id)
    session_factory = _session_factory(pg_engine)
    worker_id = "pytest:safe4-circuit"
    events: list[str] = []
    client = _ScriptedWorkerLLMClient(events=events)
    _patch_llm(monkeypatch, client)
    real_record = agent_tasks._record_provider_circuit_outcome

    async def record_spy(**kwargs: Any) -> None:
        events.append("circuit_write")
        await real_record(**kwargs)

    monkeypatch.setattr(
        agent_tasks,
        "_record_provider_circuit_outcome",
        record_spy,
    )
    work_item = await _claim_work_item(
        session_factory,
        seeded=seeded,
        worker_id=worker_id,
    )

    draft = await _generate_diagnostic_reasoning_for_work_item(
        session_factory=session_factory,
        work_item=work_item,
        worker_id=worker_id,
    )
    events.append("transaction_b")
    await _persist_diagnostic_success(
        session_factory=session_factory,
        work_item=work_item,
        worker_id=worker_id,
        result=draft,
    )

    assert events == ["provider_start", "provider_done", "circuit_write", "transaction_b"]
    state_count = await _provider_circuit_state_count(
        pg_seed_engine,
        tenant_id=tenant_id,
        provider=client.provider_name,
    )
    assert state_count == 1


async def _seed_diagnostic(
    engine: AsyncEngine,
    *,
    tenant_id: str,
) -> _SeededDiagnostic:
    seed = str(uuid.uuid4())
    session_id = str(
        derive_session_id(
            scope=SessionScope.TENANT.value,
            tenant_id=tenant_id,
            principal_id="principal-test",
            external_handle=f"{tenant_id}:{seed}:session",
        )
    )
    dispatch_id = str(derive_coordination_id(seed=f"{tenant_id}|{seed}|dispatch"))
    content = (
        "Customer says the charging cable is loose and the battery will not "
        "charge after warranty replacement guidance."
    )
    async with engine.begin() as connection:
        session = AsyncSession(bind=connection, expire_on_commit=False)
        try:
            await session.merge(TenantRow(tenant_id=tenant_id))
            await PostgresSessionPersistence(session).save_session(
                SessionRecord(
                    session_id=session_id,
                    scope=SessionScope.TENANT,
                    external_handle=f"{tenant_id}:{seed}:session",
                    tenant_id=tenant_id,
                    principal_id="principal-test",
                    opened_at=_NOW,
                    lifecycle_phase=SessionLifecyclePhase.ACTIVE,
                    lifecycle_recorded_at=_NOW,
                    lifecycle_reason=None,
                    lineage_id=derive_lineage_id(root_session_id=session_id),
                    root_session_id=session_id,
                    parent_session_id=None,
                    ancestor_session_ids=(),
                    lineage_depth=0,
                    sequence_head=-1,
                    revision=1,
                )
            )
            await PostgresCoordinationPersistence(session).record_envelope(
                CoordinationRecord(
                    coordination_id=dispatch_id,
                    message_id=str(
                        derive_message_id(seed=f"{tenant_id}|{seed}|message")
                    ),
                    sender_id="boundary:pytest",
                    recipient_id="agent:diagnostic",
                    recipient_kind="agent",
                    direction="inbound",
                    message_type="ticket",
                    priority=5,
                    status="dispatched",
                    sequence=1,
                    runtime_instance_id=str(uuid.uuid5(uuid.NAMESPACE_URL, seed)),
                    correlation_id=dispatch_id,
                    parent_coordination_id=None,
                    parent_message_id=None,
                    in_reply_to=None,
                    request_id=dispatch_id,
                    tenant_id=tenant_id,
                    governance_decision_id=None,
                    governance_chain_id=None,
                    payload_content_type="application/json",
                    payload_schema_version="1",
                    payload_body={
                        "canonical_payload": {
                            "subject": content,
                            "comment": content,
                        }
                    },
                    created_at=_NOW.isoformat(),
                    dispatched_at=_NOW.isoformat(),
                    tenant_authority_source="test",
                )
            )
            await _seed_knowledge(session, tenant_id)
            execution = await ExecutionRuntime(
                persistence=PostgresExecutionPersistence(session)
            ).request_diagnostic_execution(
                dispatch_id=dispatch_id,
                session_id=session_id,
                tenant_id=tenant_id,
                admission_token=execution_admission_token(
                    tenant_id=tenant_id,
                    admitted_at=_NOW,
                    seed=seed,
                ),
                requested_at=_NOW,
            )
            await session.flush()
        finally:
            await session.close()
    return _SeededDiagnostic(
        tenant_id=tenant_id,
        execution_id=str(execution.execution.execution_id),
        session_id=session_id,
        dispatch_id=dispatch_id,
        content=content,
    )


async def _seed_knowledge(session: AsyncSession, tenant_id: str) -> None:
    document = TenantKnowledgeDocumentRecord(
        document_id=derive_knowledge_document_id(
            tenant_id=tenant_id,
            title="SAFE4 Charging SOP",
            document_type=TenantKnowledgeDocumentType.SOP,
        ),
        tenant_id=tenant_id,
        title="SAFE4 Charging SOP",
        content=(
            "Charging support checks cable fit, battery indicator state, "
            "warranty replacement eligibility, and documented escalation."
        ),
        document_type=TenantKnowledgeDocumentType.SOP,
        status=TenantKnowledgeDocumentStatus.PENDING_INDEX,
        version=1,
        uploaded_by="principal-test",
        vector_indexed_at=None,
        created_at=_NOW,
    )
    tenant_repo = PostgresTenantConfigurationRepository(session)
    await tenant_repo.save_knowledge_document(document, expected_tenant_id=tenant_id)
    runtime = KnowledgeRuntime(
        repository=PostgresKnowledgeRepository(session),
        tenant_configuration_repository=tenant_repo,
        embedding_provider=DeterministicHashEmbeddingProvider(),
        chunker=DeterministicKnowledgeChunker(target_size=96, overlap=8, min_size=24),
        vector_index_name=get_settings().VECTOR_DEFAULT_INDEX,
        default_context_token_budget=128,
    )
    await runtime.ingest_document(tenant_id=tenant_id, document_id=document.document_id)


async def _claim_work_item(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    seeded: _SeededDiagnostic,
    worker_id: str,
) -> _DiagnosticExecutionWorkItem:
    async with _tenant_session_factory(session_factory, seeded.tenant_id) as session:
        runtime = ExecutionRuntime(persistence=PostgresExecutionPersistence(session))
        claim = await runtime.claim_execution(
            execution_id=seeded.execution_id,
            worker_id=worker_id,
            claimed_at=_NOW,
        )
        assert claim.claimed is True
        assert claim.execution is not None
        assert claim.attempt is not None
        await session.commit()
    return _DiagnosticExecutionWorkItem(
        execution_id=seeded.execution_id,
        attempt_id=str(claim.attempt.attempt_id),
        attempt_number=claim.attempt.attempt_number,
        dispatch_id=seeded.dispatch_id,
        session_id=seeded.session_id,
        tenant_id=seeded.tenant_id,
        content=seeded.content,
    )


async def _recover_claim(
    session_factory: async_sessionmaker[AsyncSession],
    execution_id: str,
    tenant_id: str,
) -> None:
    async with _tenant_session_factory(session_factory, tenant_id) as session:
        recovered = await ExecutionRuntime(
            persistence=PostgresExecutionPersistence(session)
        ).recover_stale_execution(
            execution_id=execution_id,
            stale_before=_NOW + timedelta(minutes=5),
            recovered_at=_NOW + timedelta(minutes=6),
            reason="safe4 test recovery",
        )
        assert recovered.recovered is True
        await session.commit()


async def _forensic_counts(
    engine: AsyncEngine,
    seeded: _SeededDiagnostic,
) -> dict[str, Any]:
    async with engine.connect() as connection:
        usage = (
            await connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM cognition_llm_usage_records
                    WHERE tenant_id = :tenant_id
                      AND execution_id = :execution_id
                    """
                ),
                {
                    "tenant_id": seeded.tenant_id,
                    "execution_id": seeded.execution_id,
                },
            )
        ).scalar_one()
        audit = (
            await connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM cognition_audit_records
                    WHERE tenant_id = :tenant_id
                      AND execution_id = :execution_id
                    """
                ),
                {
                    "tenant_id": seeded.tenant_id,
                    "execution_id": seeded.execution_id,
                },
            )
        ).scalar_one()
        governance = (
            await connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM governance_decisions
                    WHERE tenant_id = :tenant_id
                      AND metadata ->> 'dispatch_id' = :dispatch_id
                      AND metadata ->> 'action' = 'ai.diagnostic_classification'
                    """
                ),
                {
                    "tenant_id": seeded.tenant_id,
                    "dispatch_id": seeded.dispatch_id,
                },
            )
        ).scalar_one()
        completed_events = (
            await connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM session_events event
                    JOIN operational_sessions session
                      ON session.session_id = event.session_id
                    WHERE session.tenant_id = :tenant_id
                      AND event.session_id = :session_id
                      AND event.annotation = 'diagnostic_analysis_completed'
                    """
                ),
                {
                    "tenant_id": seeded.tenant_id,
                    "session_id": seeded.session_id,
                },
            )
        ).scalar_one()
        retrieved_citations = (
            await connection.execute(
                text(
                    """
                    SELECT metadata -> 'retrieved_citations'
                    FROM cognition_llm_usage_records
                    WHERE tenant_id = :tenant_id
                      AND execution_id = :execution_id
                    LIMIT 1
                    """
                ),
                {
                    "tenant_id": seeded.tenant_id,
                    "execution_id": seeded.execution_id,
                },
            )
        ).scalar_one_or_none()
    return {
        "usage": usage,
        "audit": audit,
        "governance": governance,
        "completed_events": completed_events,
        "retrieved_citations": retrieved_citations,
    }


async def _provider_circuit_state_count(
    engine: AsyncEngine,
    *,
    tenant_id: str,
    provider: str,
) -> int:
    async with engine.connect() as connection:
        return int(
            (
                await connection.execute(
                    text(
                        """
                        SELECT count(*)
                        FROM provider_circuit_states
                        WHERE tenant_id = :tenant_id
                          AND provider_name = :provider
                        """
                    ),
                    {"tenant_id": tenant_id, "provider": provider},
                )
            ).scalar_one()
        )


def _patch_llm(
    monkeypatch: pytest.MonkeyPatch,
    client: _ScriptedWorkerLLMClient,
) -> None:
    monkeypatch.setattr(agent_tasks, "_diagnostic_llm_client", lambda: client)
    monkeypatch.setattr(agent_tasks, "get_initialized_quota_runtime", lambda: None)


def _session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )


def _pooled_test_engine(*, pool_size: int) -> AsyncEngine:
    dsn = os.environ.get(TEST_DATABASE_URL_ENV)
    skip_reason = database_url_skip_reason()
    if dsn is None or skip_reason is not None:
        pytest.skip(skip_reason or f"requires {TEST_DATABASE_URL_ENV}")
    engine_config = build_database_engine_config(dsn, connect_timeout=30.0)
    return create_async_engine(
        engine_config.async_url,
        future=True,
        pool_pre_ping=True,
        pool_size=pool_size,
        max_overflow=0,
        pool_timeout=1,
        connect_args=engine_config.connect_args,
    )


def _tenant_session(
    engine: AsyncEngine,
    tenant_id: str,
) -> "_TenantSession":
    session_factory = _session_factory(engine)
    return _TenantSession(session_factory, tenant_id)


class _TenantSession:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        tenant_id: str,
    ) -> None:
        self._session_factory = session_factory
        self._tenant_id = tenant_id
        self._session: AsyncSession | None = None
        self._previous_tenant: str | None = None

    async def __aenter__(self) -> AsyncSession:
        self._previous_tenant = get_current_tenant()
        set_current_tenant(self._tenant_id)
        self._session = self._session_factory()
        await _set_transaction_tenant(self._session, self._tenant_id)
        return self._session

    async def __aexit__(self, *_exc: object) -> None:
        try:
            if self._session is not None:
                await self._session.close()
        finally:
            set_current_tenant(self._previous_tenant)


def _tenant_session_factory(
    session_factory: async_sessionmaker[AsyncSession],
    tenant_id: str,
) -> _TenantSession:
    return _TenantSession(session_factory, tenant_id)

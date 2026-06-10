from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from app.boundary.adapters.builtin import ZendeskWebhookAdapter
from app.boundary.contracts.requests import BoundaryIngressRequest
from app.boundary.ingress import BoundaryIngressRuntime
from app.boundary.models.payload import IngressPayload
from app.boundary.models.source import BoundarySource
from app.boundary.persistence import PostgresBoundaryPersistence
from app.boundary.registry import BoundaryAdapterRegistry
from app.coordination.persistence import PostgresCoordinationPersistence
from app.coordination.runtime import CoordinationRuntime
from app.core.config import get_settings
from app.db.session import (
    dispose_engine,
    get_owner_session_factory,
    reset_engine_state,
)
from app.execution import ExecutionRuntime, PostgresExecutionPersistence
from app.governance.persistence import PostgresGovernanceRepository
from app.identity import AuthorityContext
from app.runtime import ExecutionGovernanceRuntime
from app.services.dispatch_service import DispatchService
from app.session.persistence import PostgresSessionPersistence
from app.tenant.enums import TenantExecutionGovernanceStatus
from app.tenant.persistence import PostgresTenantConfigurationRepository
from app.tenant.runtime import TenantConfigurationRuntime
from tests.conftest import (
    TEST_DATABASE_URL_ENV,
    database_url_skip_reason,
    set_pg_rls_tenant,
)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "load: mark burst/load tests")


class TimingCollector:
    def __init__(self) -> None:
        self._durations: list[float] = []

    def record(self, duration_ms: float) -> None:
        self._durations.append(duration_ms)

    def p95(self) -> float:
        if not self._durations:
            return 0.0
        sorted_d = sorted(self._durations)
        idx = int(len(sorted_d) * 0.95)
        return sorted_d[min(idx, len(sorted_d) - 1)]

    def p50(self) -> float:
        if not self._durations:
            return 0.0
        sorted_d = sorted(self._durations)
        idx = int(len(sorted_d) * 0.50)
        return sorted_d[min(idx, len(sorted_d) - 1)]

    def p99(self) -> float:
        if not self._durations:
            return 0.0
        sorted_d = sorted(self._durations)
        idx = int(len(sorted_d) * 0.99)
        return sorted_d[min(idx, len(sorted_d) - 1)]

    def max(self) -> float:
        return max(self._durations) if self._durations else 0.0

    @property
    def count(self) -> int:
        return len(self._durations)


class NoOpExecutionPublisher:
    """Records execution publish intents without touching Celery."""

    def __init__(self) -> None:
        self.published: list[str] = []

    async def publish_execution(
        self,
        execution_id: str,
        *,
        tenant_id: str,
    ) -> None:
        del tenant_id
        self.published.append(execution_id)


@pytest.fixture
def timing_collector() -> TimingCollector:
    return TimingCollector()


@pytest.fixture
def suppress_supervisor_enqueue(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.workers.agent_tasks.evaluate_session_supervisor.apply_async",
        lambda *args, **kwargs: None,
    )


@pytest.fixture
def suppress_semantic_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Bypasses validate_governance_terms() for burst tests.

    Semantic validation correctness is tested in unit tests. Burst tests prove
    infrastructure correctness: concurrency, tenant isolation, and pipeline
    completeness.
    """

    from app.cognition.semantic import SemanticPreservationResult

    def bypass_validate_governance_terms(
        *,
        canonical_text: str,
        output_text: str,
        allowed_text: str | None = None,
    ) -> SemanticPreservationResult:
        del canonical_text, output_text, allowed_text
        return SemanticPreservationResult(
            canonical_terms=(),
            output_terms=(),
            missing_terms=(),
            introduced_terms=(),
        )

    monkeypatch.setattr(
        "app.cognition.semantic.validate_governance_terms",
        bypass_validate_governance_terms,
    )
    monkeypatch.setattr(
        "app.cognition.diagnostic_runtime.validate_governance_terms",
        bypass_validate_governance_terms,
    )


@pytest.fixture(autouse=True)
def isolate_global_quota_runtime() -> None:
    """Prevent app-construction quota runtime state leaking across tests."""

    from app.agents.runtime import quota_runtime

    quota_runtime._quota_runtime = None
    try:
        yield
    finally:
        quota_runtime._quota_runtime = None


@pytest_asyncio.fixture
async def committed_burst_seed(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[
    dict[str, Callable[[str], Awaitable[None] | Awaitable[str]]]
]:
    """
    Creates committed dispatch-chain state visible to independent sessions.
    """

    dsn = os.environ.get(TEST_DATABASE_URL_ENV)
    skip_reason = database_url_skip_reason()
    if dsn is None or skip_reason is not None:
        pytest.skip(skip_reason or f"requires {TEST_DATABASE_URL_ENV}")

    owner_dsn = _owner_database_url_for_test(dsn) or dsn
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("ALEMBIC_DATABASE_URL", owner_dsn)
    monkeypatch.setenv("DB_POOL_SIZE", "40")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "10")
    monkeypatch.setenv("DB_POOL_TIMEOUT", "60")
    get_settings.cache_clear()
    reset_engine_state()

    lock_session = get_owner_session_factory()()
    await lock_session.execute(
        text(
            "SELECT pg_advisory_lock("
            "hashtext('operious_load_tests')::bigint"
            ")"
        )
    )
    seeded: dict[str, list[str]] = {}

    async def seed_tenant(tenant_id: str) -> None:
        if tenant_id in seeded:
            return
        async with get_owner_session_factory()() as session:
            await _delete_tenant_data(session, tenant_id)
            runtime = TenantConfigurationRuntime(
                repository=PostgresTenantConfigurationRepository(session)
            )
            await runtime.configure_execution_governance(
                tenant_id=tenant_id,
                execution_quota=100_000,
                throughput_limit=100_000,
                throughput_window_minutes=60,
                governance_budget_limit=100_000,
                governance_budget_window_minutes=60,
                circuit_failure_threshold=100_000,
                circuit_window_minutes=60,
                circuit_cooldown_minutes=1,
                configured_by="burst-seed",
                status=TenantExecutionGovernanceStatus.ACTIVE,
                approval=_approved_execution_governance_change(tenant_id),
                metadata={"origin": "burst_seed"},
            )
            await session.commit()
        seeded[tenant_id] = []

    async def seed_execution(tenant_id: str) -> str:
        if tenant_id not in seeded:
            await seed_tenant(tenant_id)

        ordinal = len(seeded[tenant_id]) + 1
        external_id = f"{tenant_id}-ticket-{ordinal}"
        raw_content = "My Anker PowerCore stopped charging during travel."

        async with get_owner_session_factory()() as session:
            ingress_runtime = BoundaryIngressRuntime(
                adapters=BoundaryAdapterRegistry([ZendeskWebhookAdapter()]),
                persistence=PostgresBoundaryPersistence(session),
            )
            envelope = await ingress_runtime.ingest(
                BoundaryIngressRequest(
                    source=BoundarySource(
                        source_type=ZendeskWebhookAdapter().source_type,
                        source_id="ticket-email",
                        tenant_id=tenant_id,
                        display_name="burst seed email",
                        metadata={"language_code": "en"},
                    ),
                    adapter_name=ZendeskWebhookAdapter.DEFAULT_NAME,
                    payload=IngressPayload(
                        body={
                            "event_id": external_id,
                            "ticket_id": external_id,
                            "type": "ticket.comment_created",
                            "subject": raw_content,
                            "comment": raw_content,
                            "status": "open",
                        },
                        content_type="application/json",
                    ),
                    correlation_id=external_id,
                    request_id=external_id,
                    authority=AuthorityContext.from_raw(tenant_id=tenant_id),
                    metadata={
                        "ticket.external_id": external_id,
                        "ticket.channel": "email",
                        "ticket.language_code": "en",
                    },
                )
            )
            assert envelope.error is None, f"boundary ingest failed: {envelope.error}"
            assert envelope.result is not None
            assert envelope.result.event_id is not None
            ingress_id = str(envelope.result.ingress_id)
            await session.commit()

        async with get_owner_session_factory()() as session:
            execution_runtime = ExecutionRuntime(
                persistence=PostgresExecutionPersistence(session)
            )
            service = DispatchService(
                coordination_runtime=CoordinationRuntime(
                    governance_runtime=_dispatch_governance_runtime(),
                    persistence=PostgresCoordinationPersistence(session),
                    registry=_dispatch_coordination_registry(),
                ),
                boundary_ingress_repository=PostgresBoundaryPersistence(session),
                session_repository=PostgresSessionPersistence(session),
                execution_runtime=execution_runtime,
                execution_publisher=NoOpExecutionPublisher(),
                execution_governance_runtime=ExecutionGovernanceRuntime(
                    tenant_configuration_repository=(
                        PostgresTenantConfigurationRepository(session)
                    ),
                    execution_persistence=PostgresExecutionPersistence(session),
                    governance_repository=PostgresGovernanceRepository(session),
                ),
            )
            dispatch = await service.dispatch(
                ingress_id=ingress_id,
                tenant_id=tenant_id,
            )
            assert dispatch.halted is False, dispatch.halt_reason
            assert dispatch.execution_id is not None
            execution_id = dispatch.execution_id
            await session.commit()

        seeded[tenant_id].append(execution_id)
        return execution_id

    try:
        try:
            yield {
                "seed_tenant": seed_tenant,
                "seed_execution": seed_execution,
            }
        finally:
            async with get_owner_session_factory()() as session:
                for tenant_id in seeded:
                    await _delete_tenant_data(session, tenant_id)
                await session.commit()
    finally:
        try:
            await lock_session.execute(
                text(
                    "SELECT pg_advisory_unlock("
                    "hashtext('operious_load_tests')::bigint"
                    ")"
                )
            )
            await lock_session.commit()
        finally:
            await lock_session.close()
            await dispose_engine()
        get_settings.cache_clear()
        reset_engine_state()


async def assert_cross_tenant_isolation(
    restricted_session: AsyncSession,
    querying_as: str,
    must_not_see_tenant: str,
) -> None:
    await set_pg_rls_tenant(restricted_session, querying_as)
    result = await restricted_session.execute(
        text(
            "SELECT COUNT(*) FROM operational_sessions "
            "WHERE tenant_id = :other"
        ),
        {"other": must_not_see_tenant},
    )
    count = result.scalar()
    assert count == 0, (
        "Cross-tenant contamination: querying as "
        f"{querying_as!r} can see {count} sessions "
        f"from {must_not_see_tenant!r}. RLS failed."
    )


def _owner_database_url_for_test(raw: str) -> str | None:
    url = make_url(raw)
    if url.username == "operious":
        return None
    owner_url = url.set(username="operious", password="operious")
    return owner_url.render_as_string(hide_password=False)


def _approved_execution_governance_change(tenant_id: str) -> Any:
    from app.sop_intelligence import ApprovalRecord, ApprovalStatus

    approval_id = uuid.uuid5(
        uuid.UUID("f4ff1200-0940-5537-9752-c7693db8b5f6"),
        f"{tenant_id}|execution_governance|burst_seed",
    )
    return ApprovalRecord(
        approval_id=str(approval_id),
        tenant_id=tenant_id,
        document_id="execution_governance",
        proposed_change="execution_governance_configure",
        evidence_sessions=(),
        confidence=1.0,
        status=ApprovalStatus.APPROVED.value,
        proposed_by="burst-seed",
        reviewed_by="burst-seed",
        created_at="2026-05-25T00:00:00+00:00",
        metadata={"origin": "burst_seed"},
    )


def _dispatch_coordination_registry() -> Any:
    from app.coordination.models.participants import CoordinationParticipant
    from app.coordination.registry import CoordinationRegistry

    registry = CoordinationRegistry()
    registry.register(
        CoordinationParticipant(
            participant_id="runtime:boundary-ingress",
            kind="runtime",
        )
    )
    registry.register(
        CoordinationParticipant(
            participant_id="agent:ticket-triage",
            kind="agent",
        )
    )
    return registry


def _dispatch_governance_runtime() -> Any:
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
    from app.governance.enums import EnforcementStage
    from app.governance.evaluators.engine import PolicyEvaluationEngine
    from app.governance.policies.chain import PolicyChain
    from app.services.dispatch_service import DispatchCommunicationPolicy

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
    return GovernanceRuntime(
        engine=PolicyEvaluationEngine(),
        handler_registry=registry,
        chains={
            EnforcementStage.PRE_EXECUTION: PolicyChain(
                chain_id="dispatch.communication.pre_execution",
                stage=EnforcementStage.PRE_EXECUTION,
                policies=(DispatchCommunicationPolicy(),),
            )
        },
        persistence=None,
    )


async def _delete_tenant_data(session: AsyncSession, tenant_id: str) -> None:
    await session.execute(
        text(
            """
            DELETE FROM execution_outbox
            WHERE execution_id IN (
                SELECT execution_id
                FROM execution_records
                WHERE tenant_id = :t
            )
            """
        ),
        {"t": tenant_id},
    )
    await session.execute(
        text(
            """
            DELETE FROM execution_attempts
            WHERE execution_id IN (
                SELECT execution_id
                FROM execution_records
                WHERE tenant_id = :t
            )
            """
        ),
        {"t": tenant_id},
    )
    await session.execute(
        text("DELETE FROM cognition_audit_records WHERE tenant_id = :t"),
        {"t": tenant_id},
    )
    await session.execute(
        text("DELETE FROM cognition_llm_usage_records WHERE tenant_id = :t"),
        {"t": tenant_id},
    )
    await session.execute(
        text("DELETE FROM cognition_semantic_rejection_records WHERE tenant_id = :t"),
        {"t": tenant_id},
    )
    await session.execute(
        text("DELETE FROM escalation_outbox WHERE tenant_id = :t"),
        {"t": tenant_id},
    )
    await session.execute(
        text("DELETE FROM escalation_records WHERE tenant_id = :t"),
        {"t": tenant_id},
    )
    await session.execute(
        text(
            """
            DELETE FROM governance_enforcement_actions
            WHERE decision_id IN (
                SELECT decision_id
                FROM governance_decisions
                WHERE tenant_id = :t
            )
            """
        ),
        {"t": tenant_id},
    )
    await session.execute(
        text(
            """
            DELETE FROM governance_traces
            WHERE decision_id IN (
                SELECT decision_id
                FROM governance_decisions
                WHERE tenant_id = :t
            )
            """
        ),
        {"t": tenant_id},
    )
    await session.execute(
        text("DELETE FROM governance_decisions WHERE tenant_id = :t"),
        {"t": tenant_id},
    )
    await session.execute(
        text(
            """
            DELETE FROM session_correlations
            WHERE session_id IN (
                SELECT session_id
                FROM operational_sessions
                WHERE tenant_id = :t
            )
            """
        ),
        {"t": tenant_id},
    )
    await session.execute(
        text(
            """
            DELETE FROM session_events
            WHERE session_id IN (
                SELECT session_id
                FROM operational_sessions
                WHERE tenant_id = :t
            )
            """
        ),
        {"t": tenant_id},
    )
    await session.execute(
        text("DELETE FROM coordination_envelopes WHERE tenant_id = :t"),
        {"t": tenant_id},
    )
    await session.execute(
        text("DELETE FROM case_approval_outbox WHERE tenant_id = :t"),
        {"t": tenant_id},
    )
    await session.execute(
        text("DELETE FROM case_approval_records WHERE tenant_id = :t"),
        {"t": tenant_id},
    )
    await session.execute(
        text("DELETE FROM operational_sessions WHERE tenant_id = :t"),
        {"t": tenant_id},
    )
    await session.execute(
        text("DELETE FROM dead_letter_tasks WHERE tenant_id = :t"),
        {"t": tenant_id},
    )
    await session.execute(
        text("DELETE FROM resolution_outbound_drafts WHERE tenant_id = :t"),
        {"t": tenant_id},
    )
    await session.execute(
        text("DELETE FROM resolution_proposals WHERE tenant_id = :t"),
        {"t": tenant_id},
    )
    await session.execute(
        text("DELETE FROM execution_records WHERE tenant_id = :t"),
        {"t": tenant_id},
    )
    await session.execute(
        text("DELETE FROM ingress_dispatch_outbox WHERE tenant_id = :t"),
        {"t": tenant_id},
    )
    await session.execute(
        text("DELETE FROM boundary_ingress WHERE tenant_id = :t"),
        {"t": tenant_id},
    )
    await session.execute(
        text("DELETE FROM provider_circuit_states WHERE tenant_id = :t"),
        {"t": tenant_id},
    )
    await session.execute(
        text("DELETE FROM provider_quota_records WHERE tenant_id = :t"),
        {"t": tenant_id},
    )
    await session.execute(
        text("DELETE FROM tenant_execution_circuit_breakers WHERE tenant_id = :t"),
        {"t": tenant_id},
    )
    await session.execute(
        text(
            "DELETE FROM tenant_execution_governance_configurations "
            "WHERE tenant_id = :t"
        ),
        {"t": tenant_id},
    )
    await session.execute(
        text("DELETE FROM data_protection_erasure_requests WHERE tenant_id = :t"),
        {"t": tenant_id},
    )
    await session.execute(
        text("DELETE FROM data_protection_legal_holds WHERE tenant_id = :t"),
        {"t": tenant_id},
    )
    await session.execute(
        text("DELETE FROM tenant_data_retention_policies WHERE tenant_id = :t"),
        {"t": tenant_id},
    )
    await session.execute(
        text("DELETE FROM data_protection_data_keys WHERE tenant_id = :t"),
        {"t": tenant_id},
    )
    await session.execute(
        text("DELETE FROM tenants WHERE tenant_id = :t"),
        {"t": tenant_id},
    )

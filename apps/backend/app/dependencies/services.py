"""Service / repository dependency providers.

Each provider composes one substrate-shaped dependency from its
concrete collaborators (request-scoped ``AsyncSession``, settings,
shared infra clients). Providers are cheap to construct (no state,
no caches), so we mint a fresh instance per request — that keeps
them safe to await without worrying about cross-request leakage.

Doctrine
────────

* **Routers depend on the Protocol type**, never the concrete
  Postgres class. ``Depends(get_governance_repository)`` is annotated
  ``-> BaseGovernanceRepository`` so handlers cannot import
  ``PostgresGovernanceRepository`` directly — the composition root
  is the single seam between "what the router needs" and "which
  backend currently satisfies it". This is what enables PR-B1's
  in-memory ↔ Postgres swap doctrine to land at runtime without
  touching any router.
* **No service-layer caching**. Repositories close their session
  (via the request-scoped ``get_db_session`` provider) at request
  end. Stale-cache hazards do not exist at this layer.
* **No raw HTTP** in providers. Network-touching dependencies
  (Auth0 JWKS fetch, Redis pings) live in their own modules and
  are constructed at app-boot via the composition root, not via
  request-scoped providers — once-per-request fetches against
  external services are a substrate-wide performance footgun
  the platform refuses by construction.

Phase 3.2 substrate factories
─────────────────────────────

Every substrate that landed a Postgres backend in PR-B2..B7 gets
exactly one factory here. Routers reach the substrate's
persistence Protocol via ``Depends(get_<substrate>_repository)``.
Adding a substrate is additive — never modify an existing factory
to widen its surface.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, cast
import uuid

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.runtime.quota_runtime import TenantQuotaRuntime
from app.arbitration.persistence import (
    ArbitrationPersistenceProtocol,
    PostgresArbitrationPersistence,
)
from app.boundary.persistence import (
    BoundaryPersistenceProtocol,
    PostgresBoundaryPersistence,
)
from app.coordination.persistence import (
    CoordinationPersistenceProtocol,
    PostgresCoordinationPersistence,
)
from app.coordination.registry import CoordinationRegistry
from app.coordination.models.participants import CoordinationParticipant
from app.coordination.runtime import CoordinationRuntime
from app.cognition import CognitionRuntime
from app.cognition.persistence import PostgresCognitionUsagePersistence
from app.core.config import get_settings
from app.core.admission import admission_thresholds_from_settings
from app.core.redis import get_redis_client
from app.dependencies.database import get_db_session, get_session_factory
from app.execution import (
    ExecutionOutboxClaimId,
    ExecutionOutboxClaimLost,
    ExecutionRuntime,
    PostgresExecutionPersistence,
)
from app.execution.celery_publisher import CeleryExecutionPublisher
from app.execution.publisher import ExecutionPublisher, QueueBackpressureCheck
from app.events import PostgresOperationalEventPersistence
from app.events.read_service import OperationalEventReader
from app.escalation.celery_publisher import CeleryEscalationPublisher
from app.escalation.persistence import PostgresEscalationPersistence
from app.escalation.publisher import EscalationPublisher
from app.escalation.runtime import EscalationAgentRuntime
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
from app.governance.persistence import (
    BaseGovernanceRepository,
    PostgresGovernanceRepository,
)
from app.governance.policies.chain import PolicyChain
from app.knowledge import (
    DeterministicHashEmbeddingProvider,
    DeterministicKnowledgeChunker,
    KnowledgeRuntime,
)
from app.knowledge.persistence import PostgresKnowledgeRepository
from app.observability.persistence import (
    PostgresOperationalObservabilityPersistence,
)
from app.observability.runtime import OperationalObservabilityRuntime
from app.runtime import (
    ExecutionGovernanceRuntime,
    ProviderCircuitBreaker,
    TenantCoordinationTopologyRuntimeProvider,
    make_postgres_dispatch_arbitration_runtime,
)
from app.runtime.tenant_production_hardening import (
    TenantProductionHardeningRuntime,
)
from app.services.audit_export_service import AuditExportService
from app.services.cognition_service import CognitionService
from app.services.dispatch_service import (
    DispatchCommunicationPolicy,
    DispatchService,
)
from app.services.escalation_service import EscalationService
from app.hardening.admission import (
    AdmissionDecision,
    AdmissionGate,
    AdmissionOutcome,
)
from app.hardening.admission.gate import AdmissionRedisClient
from app.dependencies.authority import require_tenant_scope
from app.services.health_service import HealthService
from app.services.admission_service import (
    AdmissionService,
    measure_db_pool_wait_ms,
)
from app.services.knowledge_service import KnowledgeService
from app.services.operational_event_service import OperationalEventService
from app.services.operational_observability_service import (
    OperationalObservabilityService,
)
from app.services.quota_operations_service import QuotaOperationsService
from app.services.queue_operations_service import QueueOperationsService
from app.services.sop_intelligence_service import SOPIntelligenceService
from app.services.ticket_ingress_service import TicketIngressService
from app.qa.persistence import PostgresQAPersistence
from app.queues import DIAGNOSTIC_QUEUE_PRIORITY
from app.session.persistence import (
    PostgresSessionPersistence,
    SessionPersistenceProtocol,
)
from app.sop_intelligence.persistence import PostgresSOPApprovalPersistence
from app.sop_intelligence.runtime import SOPIntelligenceRuntime
from app.supervisor.persistence import (
    BaseSupervisorRepository,
    PostgresSupervisorRepository,
)
from app.services.tenant_configuration_service import (
    TenantConfigurationService,
)
from app.tenant.credentials import TenantCredentialEncryptor
from app.tenant.enums import TenantChannelType
from app.tenant.persistence import PostgresTenantConfigurationRepository
from app.tenant.runtime import TenantConfigurationRuntime

if TYPE_CHECKING:
    from app.services.batch_ingest_service import BatchIngestService


async def get_health_service() -> HealthService:
    """Construct `HealthService` with lazy readiness collaborators."""
    return HealthService(
        settings=get_settings(),
        session_factory_provider=get_session_factory,
        redis_provider=get_redis_client,
    )


def get_quota_runtime(request: Request) -> TenantQuotaRuntime:
    """Return the application-scoped tenant quota runtime."""

    return cast(TenantQuotaRuntime, request.app.state.quota_runtime)


# ─── Phase 3.2 substrate repository factories ───────────────────────────


def get_governance_repository(
    session: AsyncSession = Depends(get_db_session),
) -> BaseGovernanceRepository:
    """Return the Postgres governance repository for this request.

    Return type is annotated to the Protocol so handlers cannot
    accidentally couple to the concrete backend.
    """
    return PostgresGovernanceRepository(session)


def get_session_repository(
    session: AsyncSession = Depends(get_db_session),
) -> SessionPersistenceProtocol:
    """Return the Postgres session-persistence backend for this request."""
    return PostgresSessionPersistence(session)


def get_coordination_repository(
    session: AsyncSession = Depends(get_db_session),
) -> CoordinationPersistenceProtocol:
    """Return the Postgres coordination-persistence backend for this request."""
    return PostgresCoordinationPersistence(session)


def get_arbitration_repository(
    session: AsyncSession = Depends(get_db_session),
) -> ArbitrationPersistenceProtocol:
    """Return the Postgres arbitration-persistence backend for this request."""
    return PostgresArbitrationPersistence(session)


def get_boundary_repository(
    session: AsyncSession = Depends(get_db_session),
) -> BoundaryPersistenceProtocol:
    """Return the Postgres boundary-persistence backend for this request."""
    return PostgresBoundaryPersistence(session)


def get_ticket_ingress_service(
    session: AsyncSession = Depends(get_db_session),
) -> TicketIngressService:
    """Return the ticket-ingress write service for this request."""
    settings = get_settings()
    tenant_runtime: TenantConfigurationRuntime | None = None
    if settings.TENANT_CREDENTIAL_MASTER_KEY:
        tenant_runtime = TenantConfigurationRuntime(
            repository=PostgresTenantConfigurationRepository(session),
            credential_encryptor=TenantCredentialEncryptor(
                platform_master_key=settings.TENANT_CREDENTIAL_MASTER_KEY,
            ),
        )
    session_factory = get_session_factory()
    admission_service = AdmissionService(
        gate=AdmissionGate(
            redis_client=cast(AdmissionRedisClient, get_redis_client()),
            thresholds=admission_thresholds_from_settings(settings),
        ),
        session_factory=session_factory,
        db_pool_wait_provider=lambda: measure_db_pool_wait_ms(session_factory),
    )
    return TicketIngressService(
        persistence=PostgresBoundaryPersistence(session),
        session=session,
        tenant_configuration_runtime=tenant_runtime,
        admission_service=admission_service,
        webhook_queue_by_channel={
            TenantChannelType.EMAIL: DIAGNOSTIC_QUEUE_PRIORITY,
            TenantChannelType.LARK: DIAGNOSTIC_QUEUE_PRIORITY,
            TenantChannelType.SHULEX: DIAGNOSTIC_QUEUE_PRIORITY,
            TenantChannelType.WHATSAPP: DIAGNOSTIC_QUEUE_PRIORITY,
        },
    )


def get_admission_service() -> AdmissionService:
    """Return the platform admission service for inbound workloads."""
    settings = get_settings()
    session_factory = get_session_factory()
    return AdmissionService(
        gate=AdmissionGate(
            redis_client=cast(AdmissionRedisClient, get_redis_client()),
            thresholds=admission_thresholds_from_settings(settings),
        ),
        session_factory=session_factory,
        db_pool_wait_provider=lambda: measure_db_pool_wait_ms(session_factory),
    )


async def check_batch_ingest_admission(
    expected_tenant_id: str = Depends(require_tenant_scope),
    admission_service: AdmissionService = Depends(get_admission_service),
) -> AdmissionDecision:
    """Fail closed before batch-ingest service processing begins."""
    evaluated_second = datetime.now(timezone.utc).replace(microsecond=0)
    correlation_id = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"batch:{expected_tenant_id}:{evaluated_second.isoformat()}",
        )
    )
    decision = await admission_service.evaluate_and_persist(
        queue_names=DIAGNOSTIC_QUEUE_PRIORITY,
        tenant_id=expected_tenant_id,
        channel="batch_ingest",
        request_correlation_id=correlation_id,
    )
    if decision.outcome is AdmissionOutcome.ADMIT:
        return decision
    reason = decision.reason.value if decision.reason is not None else "UNKNOWN"
    headers = {
        "X-Operious-Admission-Decision-Id": str(decision.decision_id),
    }
    if decision.outcome is AdmissionOutcome.DEFER:
        headers["Retry-After"] = str(decision.retry_after_seconds)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "admission_deferred",
                "reason": reason,
                "decision_id": str(decision.decision_id),
                "retry_after_seconds": decision.retry_after_seconds,
            },
            headers=headers,
        )
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={
            "code": "admission_rejected",
            "reason": reason,
            "decision_id": str(decision.decision_id),
        },
        headers=headers,
    )


def get_execution_publisher() -> ExecutionPublisher:
    """Return the execution publisher transport boundary."""
    return CeleryExecutionPublisher()


async def get_dispatch_service(
    session: AsyncSession = Depends(get_db_session),
    execution_publisher: ExecutionPublisher = Depends(
        get_execution_publisher
    ),
) -> AsyncIterator[DispatchService]:
    """Return the PR-W3 dispatch service for this request."""
    execution_runtime = ExecutionRuntime(
        persistence=PostgresExecutionPersistence(session),
    )
    deferred_execution_publisher = _DeferredExecutionPublisher(
        delegate=execution_publisher,
        execution_runtime=execution_runtime,
        session=session,
        publisher_id="api:dispatch",
    )
    deferred_escalation_publisher = _DeferredEscalationPublisher(
        delegate=CeleryEscalationPublisher(),
        escalation_runtime=EscalationAgentRuntime(
            escalation_persistence=PostgresEscalationPersistence(session),
            governance_repository=PostgresGovernanceRepository(session),
            session_persistence=PostgresSessionPersistence(session),
        ),
        session=session,
        publisher_id="api:dispatch",
    )
    tenant_topology_provider = TenantCoordinationTopologyRuntimeProvider(
        tenant_configuration_runtime=TenantConfigurationRuntime(
            repository=PostgresTenantConfigurationRepository(session),
        )
    )
    service = DispatchService(
        coordination_runtime=CoordinationRuntime(
            governance_runtime=_dispatch_governance_runtime(
                PostgresGovernanceRepository(session)
            ),
            persistence=PostgresCoordinationPersistence(session),
            registry=_dispatch_coordination_registry(),
        ),
        boundary_ingress_repository=PostgresBoundaryPersistence(session),
        session_repository=PostgresSessionPersistence(session),
        execution_runtime=execution_runtime,
        execution_publisher=deferred_execution_publisher,
        execution_governance_runtime=ExecutionGovernanceRuntime(
            tenant_configuration_repository=PostgresTenantConfigurationRepository(
                session
            ),
            execution_persistence=PostgresExecutionPersistence(session),
            governance_repository=PostgresGovernanceRepository(session),
            provider_circuit_breaker=ProviderCircuitBreaker(session=session),
            default_provider_name="anthropic",
        ),
        escalation_publisher=deferred_escalation_publisher,
        dispatch_arbitration_runtime=(
            make_postgres_dispatch_arbitration_runtime(session=session)
        ),
        tenant_topology_runtime_provider=tenant_topology_provider.for_tenant,
    )
    try:
        yield service
        await session.commit()
        await deferred_escalation_publisher.flush()
        await deferred_execution_publisher.flush()
    except Exception:
        await session.rollback()
        raise


def get_batch_ingest_service(
    boundary_repository: BoundaryPersistenceProtocol = Depends(
        get_boundary_repository
    ),
    dispatch_service: DispatchService = Depends(get_dispatch_service),
) -> BatchIngestService:
    """Return the batch-ingest service for this request."""
    from app.services.batch_ingest_service import BatchIngestService

    return BatchIngestService(
        boundary_repository=boundary_repository,
        dispatch_service=dispatch_service,
    )


def get_supervisor_repository(
    session: AsyncSession = Depends(get_db_session),
) -> BaseSupervisorRepository:
    """Return the Postgres supervisor-persistence backend for this request."""
    return PostgresSupervisorRepository(session)


def get_escalation_service(
    session: AsyncSession = Depends(get_db_session),
) -> EscalationService:
    """Return the Command Center escalation service for this request."""
    return EscalationService(
        runtime=EscalationAgentRuntime(
            escalation_persistence=PostgresEscalationPersistence(session),
            governance_repository=PostgresGovernanceRepository(session),
            session_persistence=PostgresSessionPersistence(session),
        ),
        session=session,
    )


def get_tenant_configuration_service(
    session: AsyncSession = Depends(get_db_session),
) -> TenantConfigurationService:
    """Return the tenant-owned configuration service for this request."""
    settings = get_settings()
    runtime = TenantConfigurationRuntime(
        repository=PostgresTenantConfigurationRepository(session),
        credential_encryptor=TenantCredentialEncryptor(
            platform_master_key=settings.TENANT_CREDENTIAL_MASTER_KEY,
        ),
    )
    return TenantConfigurationService(runtime=runtime, session=session)


def get_cognition_service(
    session: AsyncSession = Depends(get_db_session),
) -> CognitionService:
    """Return the Cognition Hub lifecycle service for this request."""
    settings = get_settings()
    audit_encryptor = (
        TenantCredentialEncryptor(
            platform_master_key=settings.TENANT_CREDENTIAL_MASTER_KEY,
        )
        if settings.TENANT_CREDENTIAL_MASTER_KEY
        else None
    )
    return CognitionService(
        runtime=CognitionRuntime(
            approval_persistence=PostgresSOPApprovalPersistence(session),
            tenant_configuration_repository=(
                PostgresTenantConfigurationRepository(session)
            ),
        ),
        usage_persistence=PostgresCognitionUsagePersistence(
            session,
            audit_encryptor=audit_encryptor,
        ),
        session=session,
    )


def get_knowledge_service(
    session: AsyncSession = Depends(get_db_session),
) -> KnowledgeService:
    """Return the tenant knowledge ingestion/retrieval service."""
    settings = get_settings()
    runtime = KnowledgeRuntime(
        repository=PostgresKnowledgeRepository(session),
        tenant_configuration_repository=PostgresTenantConfigurationRepository(
            session
        ),
        embedding_provider=DeterministicHashEmbeddingProvider(),
        chunker=DeterministicKnowledgeChunker(
            target_size=settings.CHUNK_TARGET_SIZE,
            overlap=settings.CHUNK_OVERLAP,
            min_size=settings.CHUNK_MIN_SIZE,
        ),
        vector_index_name=settings.VECTOR_DEFAULT_INDEX,
        default_context_token_budget=settings.RAG_DEFAULT_CONTEXT_TOKEN_BUDGET,
    )
    return KnowledgeService(runtime=runtime, session=session)


def get_sop_intelligence_service(
    session: AsyncSession = Depends(get_db_session),
) -> SOPIntelligenceService:
    """Return the SOP intelligence proposal service for this request."""
    return SOPIntelligenceService(
        runtime=SOPIntelligenceRuntime(
            approval_persistence=PostgresSOPApprovalPersistence(session),
            session_persistence=PostgresSessionPersistence(session),
            supervisor_repository=PostgresSupervisorRepository(session),
            qa_persistence=PostgresQAPersistence(session),
            governance_repository=PostgresGovernanceRepository(session),
            tenant_configuration_repository=(
                PostgresTenantConfigurationRepository(session)
            ),
        )
    )


def get_operational_observability_service(
    session: AsyncSession = Depends(get_db_session),
) -> OperationalObservabilityService:
    """Return the tenant operational observability service."""
    return OperationalObservabilityService(
        runtime=OperationalObservabilityRuntime(
            persistence=PostgresOperationalObservabilityPersistence(session),
        ),
        session=session,
    )


def get_operational_event_service(
    session: AsyncSession = Depends(get_db_session),
) -> OperationalEventService:
    """Return the canonical event-fabric read service."""
    return OperationalEventService(
        reader=OperationalEventReader(
            persistence=PostgresOperationalEventPersistence(session),
        )
    )


def get_tenant_production_hardening_runtime(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> TenantProductionHardeningRuntime:
    """Return the tenant hardening runtime bound to request storage."""

    runtime = cast(
        TenantProductionHardeningRuntime,
        request.app.state.tenant_production_hardening_runtime,
    )
    return runtime.bind_persistence(
        event_persistence=PostgresOperationalEventPersistence(session),
        boundary_persistence=PostgresBoundaryPersistence(session),
    )


def get_audit_export_service(
    runtime: TenantProductionHardeningRuntime = Depends(
        get_tenant_production_hardening_runtime
    ),
) -> AuditExportService:
    """Return the signed audit export service."""

    return AuditExportService(runtime=runtime)


def get_quota_operations_service(
    session: AsyncSession = Depends(get_db_session),
    quota_runtime: TenantQuotaRuntime = Depends(get_quota_runtime),
) -> QuotaOperationsService:
    """Return the operator quota operations service."""

    return QuotaOperationsService(
        quota_runtime=quota_runtime,
        session=session,
    )


def get_queue_operations_service(
    session: AsyncSession = Depends(get_db_session),
) -> QueueOperationsService:
    """Return the queue operations service."""

    return QueueOperationsService(session=session)


def _dispatch_coordination_registry() -> CoordinationRegistry:
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


def _dispatch_governance_runtime(
    persistence: BaseGovernanceRepository | None = None,
) -> GovernanceRuntime:
    return GovernanceRuntime(
        engine=PolicyEvaluationEngine(),
        handler_registry=_governance_handler_registry(),
        chains={
            EnforcementStage.PRE_EXECUTION: PolicyChain(
                chain_id="dispatch.communication.pre_execution",
                stage=EnforcementStage.PRE_EXECUTION,
                policies=(DispatchCommunicationPolicy(),),
            )
        },
        persistence=persistence,
    )


def _governance_handler_registry() -> EnforcementHandlerRegistry:
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


@dataclass(frozen=True, slots=True)
class _DiagnosticExecutionIntent:
    execution_id: str
    tenant_id: str


@dataclass(frozen=True, slots=True)
class _EscalationIntent:
    governance_decision_id: str
    tenant_id: str
    session_id: str | None


class _DeferredEscalationPublisher(EscalationPublisher):
    """Request-scoped escalation outbox publisher."""

    def __init__(
        self,
        *,
        delegate: EscalationPublisher,
        escalation_runtime: EscalationAgentRuntime,
        session: AsyncSession,
        publisher_id: str,
    ) -> None:
        self._delegate = delegate
        self._escalation_runtime = escalation_runtime
        self._session = session
        self._publisher_id = publisher_id
        self._intents: list[_EscalationIntent] = []

    async def publish_governance_denial(
        self,
        *,
        governance_decision_id: str,
        tenant_id: str,
        session_id: str | None = None,
    ) -> None:
        self._intents.append(
            _EscalationIntent(
                governance_decision_id=governance_decision_id,
                tenant_id=tenant_id,
                session_id=session_id,
            )
        )

    async def flush(self) -> None:
        for intent in self._intents:
            prepared = await self._escalation_runtime.prepare_governance_denial_outbox(
                governance_decision_id=intent.governance_decision_id,
                expected_tenant_id=intent.tenant_id,
                session_id=intent.session_id,
                metadata={
                    "source_governance_decision_id": intent.governance_decision_id,
                    "source_session_id": intent.session_id,
                },
            )
            claim = await self._escalation_runtime.claim_outbox_for_escalation(
                escalation_id=prepared.escalation.escalation_id,
                publisher_id=self._publisher_id,
                expected_tenant_id=intent.tenant_id,
            )
            if not claim.claimed or claim.outbox is None:
                if claim.reason == "outbox_not_publishable:published":
                    continue
                raise EscalationOutboxPublishError(
                    prepared.escalation.escalation_id,
                    claim.reason or "outbox_claim_refused",
                )
            await self._session.commit()
            try:
                await self._delegate.publish_governance_denial(
                    governance_decision_id=intent.governance_decision_id,
                    tenant_id=intent.tenant_id,
                    session_id=intent.session_id,
                )
            except Exception as exc:
                await self._escalation_runtime.mark_outbox_failed(
                    outbox_id=claim.outbox.outbox_id,
                    claim_id=_require_outbox_claim_id(claim.outbox.claim_id),
                    error=_bounded_publish_error(exc),
                    expected_tenant_id=intent.tenant_id,
                )
                await self._session.commit()
                raise EscalationOutboxPublishError(
                    prepared.escalation.escalation_id,
                    _bounded_publish_error(exc),
                ) from exc
            await self._escalation_runtime.mark_outbox_published(
                outbox_id=claim.outbox.outbox_id,
                claim_id=_require_outbox_claim_id(claim.outbox.claim_id),
                expected_tenant_id=intent.tenant_id,
            )
            await self._session.commit()


class _DeferredExecutionPublisher(ExecutionPublisher):
    """Request-scoped outbox publisher that flushes after DB commit."""

    def __init__(
        self,
        *,
        delegate: ExecutionPublisher,
        execution_runtime: ExecutionRuntime,
        session: AsyncSession,
        publisher_id: str,
    ) -> None:
        self._delegate = delegate
        self._execution_runtime = execution_runtime
        self._session = session
        self._publisher_id = publisher_id
        self._diagnostic_executions: list[_DiagnosticExecutionIntent] = []

    async def publish_execution(
        self,
        execution_id: str,
        *,
        tenant_id: str,
    ) -> None:
        if isinstance(self._delegate, QueueBackpressureCheck):
            await self._delegate.check_backpressure(tenant_id=tenant_id)
        self._diagnostic_executions.append(
            _DiagnosticExecutionIntent(
                execution_id=execution_id,
                tenant_id=tenant_id,
            )
        )

    async def flush(self) -> None:
        for intent in self._diagnostic_executions:
            claim = await self._execution_runtime.claim_outbox_for_execution(
                execution_id=intent.execution_id,
                publisher_id=self._publisher_id,
            )
            if not claim.claimed or claim.outbox is None:
                if claim.reason == "outbox_not_publishable:published":
                    continue
                raise ExecutionOutboxPublishError(
                    intent.execution_id,
                    claim.reason or "outbox_claim_refused",
                )
            await self._session.commit()
            try:
                await self._delegate.publish_execution(
                    execution_id=intent.execution_id,
                    tenant_id=intent.tenant_id,
                )
            except Exception as exc:
                await self._execution_runtime.mark_outbox_failed(
                    outbox_id=claim.outbox.outbox_id,
                    claim_id=_require_execution_outbox_claim_id(
                        claim.outbox.claim_id
                    ),
                    error=_bounded_publish_error(exc),
                )
                await self._session.commit()
                raise ExecutionOutboxPublishError(
                    intent.execution_id,
                    _bounded_publish_error(exc),
                ) from exc
            published = await self._execution_runtime.mark_outbox_published(
                outbox_id=claim.outbox.outbox_id,
                claim_id=_require_execution_outbox_claim_id(
                    claim.outbox.claim_id
                ),
            )
            if isinstance(published, ExecutionOutboxClaimLost):
                raise ExecutionOutboxPublishError(
                    intent.execution_id,
                    published.reason,
                )
            await self._session.commit()


class ExecutionOutboxPublishError(RuntimeError):
    """Raised when a committed execution intent cannot be published."""

    def __init__(self, execution_id: str, reason: str) -> None:
        super().__init__(
            f"execution outbox publish failed for {execution_id}: {reason}"
        )
        self.execution_id = execution_id
        self.reason = reason


class EscalationOutboxPublishError(RuntimeError):
    """Raised when a committed escalation intent cannot be published."""

    def __init__(self, escalation_id: str, reason: str) -> None:
        super().__init__(
            f"escalation outbox publish failed for {escalation_id}: {reason}"
        )
        self.escalation_id = escalation_id
        self.reason = reason


def _bounded_publish_error(exc: BaseException) -> str:
    message = f"{exc.__class__.__name__}: {exc}"
    if len(message) > 240:
        return f"{message[:237]}..."
    return message


def _require_outbox_claim_id(claim_id: str | None) -> str:
    if claim_id is None:
        raise EscalationOutboxPublishError(
            "unknown",
            "claimed escalation outbox is missing claim_id",
        )
    return claim_id


def _require_execution_outbox_claim_id(
    claim_id: ExecutionOutboxClaimId | None,
) -> ExecutionOutboxClaimId:
    if claim_id is None:
        raise ExecutionOutboxPublishError(
            "unknown",
            "claimed execution outbox is missing claim_id",
        )
    return claim_id


__all__ = [
    "get_audit_export_service",
    "get_arbitration_repository",
    "get_boundary_repository",
    "get_cognition_service",
    "get_coordination_repository",
    "get_escalation_service",
    "get_governance_repository",
    "get_health_service",
    "get_knowledge_service",
    "get_operational_event_service",
    "get_operational_observability_service",
    "get_queue_operations_service",
    "get_quota_operations_service",
    "get_quota_runtime",
    "get_session_repository",
    "get_sop_intelligence_service",
    "get_supervisor_repository",
    "get_tenant_configuration_service",
]

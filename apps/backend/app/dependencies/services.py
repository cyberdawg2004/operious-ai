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
from app.agents.tools.action_governance import (
    build_action_tool_governance_runtime,
)
from app.agents.tools.actions import build_tenant_action_tool_registry
from app.agents.tools.connectors import PostgresConnectorConfigRepository
from app.agents.tools.connectors.credentials import (
    ConnectorCredentialRepository,
    ConnectorScopedCredentialRuntime,
)
from app.agents.tools.approvals import PostgresActionApprovalRepository
from app.agents.tools.connector_invocations import (
    PostgresConnectorInvocationRepository,
)
from app.agents.tools.grants import PostgresAgentActionGrantRepository
from app.agents.tools.invoker import ToolInvoker
from app.agents.tools.orchestration import ActionOrchestrationRuntime
from app.approvals.celery_publisher import CeleryCaseApprovalReviewPublisher
from app.approvals.ingress import ApprovalQueueIngressService
from app.approvals.persistence import PostgresCaseApprovalPersistence
from app.arbitration.persistence import (
    ArbitrationPersistenceProtocol,
    PostgresArbitrationPersistence,
)
from app.boundary.persistence import (
    BoundaryPersistenceProtocol,
    PostgresBoundaryPersistence,
)
from app.boundary.outbound import (
    PostgresEmailDeliveryRepository,
    PostgresOutboundSendOutboxPersistence,
    SesV2EmailSender,
    PostgresWhatsAppDeliveryRepository,
    WhatsAppGraphSender,
)
from app.boundary.translation import TranslationRuntime
from app.coordination.persistence import (
    CoordinationPersistenceProtocol,
    PostgresCoordinationPersistence,
)
from app.coordination.registry import CoordinationRegistry
from app.coordination.models.participants import CoordinationParticipant
from app.coordination.runtime import CoordinationRuntime
from app.cognition import CognitionRuntime
from app.cognition.persistence import PostgresCognitionUsagePersistence
from app.cognition.sop_approval_event_publisher import (
    PostgresSOPApprovalApplyEventProjector,
)
from app.core.config import Settings, get_settings
from app.core.admission import admission_thresholds_from_settings
from app.core.queue_depth import get_queue_depth_provider
from app.core.redis import get_redis_client
from app.data_protection.crypto import DataProtectionError, DataProtectionService
from app.data_protection.kms import build_master_key_unwrap
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
from app.events.appender import OperationalEventAppender
from app.events.read_service import OperationalEventReader
from app.escalation.celery_publisher import CeleryEscalationPublisher
from app.escalation.deferred_publisher import (
    DeferredEscalationPublisher,
)
from app.escalation.persistence import PostgresEscalationPersistence
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
    DeterministicKnowledgeChunker,
    KnowledgeRuntime,
    build_embedding_provider,
)
from app.knowledge.persistence import PostgresKnowledgeRepository
from app.knowledge.reindex_publisher import CeleryKnowledgeReindexPublisher
from app.agents.governed.sop_contradiction import SOPContradictionAgent
from app.cognition.llm_factory import build_llm_client
from app.observability.persistence import (
    PostgresOperationalObservabilityPersistence,
)
from app.observability.runtime import OperationalObservabilityRuntime
from app.runtime import (
    ExecutionGovernanceRuntime,
    ProviderCircuitBreaker,
    ResolutionGovernanceGate,
    TenantCoordinationTopologyRuntimeProvider,
    build_resolution_governance_runtime,
    make_postgres_dispatch_arbitration_runtime,
)
from app.runtime.grounding import CitationCoverageGroundingChecker
from app.runtime.tenant_production_hardening import (
    TenantProductionHardeningRuntime,
)
from app.runtime.timeline_runtime import TimelineRuntime
from app.resolution.persistence import PostgresResolutionProposalPersistence
from app.semantic import (
    SemanticCircuitBreaker,
    SemanticCircuitEventRepository,
    TextFingerprinter,
)
from app.semantic.quarantine_publisher import CelerySemanticQuarantinePublisher
from app.services.action_approval_service import ActionApprovalService
from app.services.audit_export_service import AuditExportService
from app.services.case_approval_service import CaseApprovalService
from app.services.outbound_auto_send_service import OutboundAutoSendService
from app.services.cognition_service import CognitionService
from app.services.auth0_management import Auth0ManagementClientProtocol
from app.services.conversation_service import (
    ConversationService,
    build_conversation_service,
)
from app.services.crisis_events import PostgresCrisisEventRepository
from app.services.crisis_service import CrisisService
from app.services.dispatch_service import (
    DispatchCommunicationPolicy,
    DispatchService,
)
from app.services.email_customer_reply_service import (
    EmailCustomerReplySendService,
)
from app.session.continuity import CaseContinuityRuntime
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
from app.services.quarantine_service import QuarantineService
from app.services.queue_operations_service import QueueOperationsService
from app.services.semantic_circuit_service import SemanticCircuitService
from app.services.session_read_service import SessionReadService
from app.services.sop_intelligence_service import SOPIntelligenceService
from app.services.supervisor_inbox_service import SupervisorInboxService
from app.services.ticket_ingress_service import TicketChannel, TicketIngressService
from app.services.trainer_service import TrainerRecommendationService
from app.services.whatsapp_customer_reply_service import (
    WhatsAppCustomerReplySendService,
)
from app.qa.persistence import PostgresQAPersistence
from app.queues import DIAGNOSTIC_QUEUE_PRIORITY
from app.session.persistence import (
    PostgresSessionPersistence,
    SessionPersistenceProtocol,
)
from app.session.runtime import SessionRuntime
from app.sme import build_sme_review_runtime
from app.sop_intelligence.persistence import PostgresSOPApprovalPersistence
from app.sop_intelligence.runtime import SOPIntelligenceRuntime
from app.supervisor.persistence import (
    BaseSupervisorRepository,
    PostgresSupervisorRepository,
)
from app.services.tenant_configuration_service import (
    TenantConfigurationService,
)
from app.services.tenant_config_change_request_service import (
    TenantConfigChangeRequestService,
)
from app.services.tenant_lifecycle_service import TenantLifecycleService
from app.tenant.change_requests import (
    PostgresTenantConfigChangeRequestRepository,
)
from app.tenant.credentials import (
    TenantCredentialCodec,
    TenantCredentialEncryptor,
    build_tenant_credential_encryptor_from_settings,
)
from app.tenant.enums import TenantChannelType
from app.tenant.exceptions import TenantCredentialEncryptionError
from app.tenant.lifecycle import PostgresTenantLifecycleRepository
from app.tenant.persistence import PostgresTenantConfigurationRepository
from app.tenant.runtime import TenantConfigurationRuntime
from app.trainer.persistence import PostgresTrainingRecommendationRepository
from app.work_orders.persistence import PostgresWorkOrderRepository

if TYPE_CHECKING:
    from app.services.batch_ingest_service import BatchIngestService
    from app.services.work_order_fulfillment_receipt_service import (
        WorkOrderFulfillmentReceiptService,
    )


async def get_health_service() -> HealthService:
    """Construct `HealthService` with lazy readiness collaborators."""
    return HealthService(
        settings=get_settings(),
        session_factory_provider=get_session_factory,
        redis_provider=get_redis_client,
        queue_depth_provider_factory=get_queue_depth_provider,
    )


def get_quota_runtime(request: Request) -> TenantQuotaRuntime:
    """Return the application-scoped tenant quota runtime."""

    return cast(TenantQuotaRuntime, request.app.state.quota_runtime)


def _build_sop_contradiction_agent(
    session: AsyncSession,
    settings: Settings,
) -> SOPContradictionAgent | None:
    """Build the SOPContradictionAgent for KB ingestion and analysis.

    Returns None in environments where the LLM client cannot be built
    (no credentials) — the KnowledgeRuntime gracefully omits the check.
    """
    try:
        tenant_config_repo = PostgresTenantConfigurationRepository(
            session,
            data_protection=_data_protection_service(session),
        )
        return SOPContradictionAgent(
            llm_client=build_llm_client(settings),
            tenant_configuration_repository=tenant_config_repo,
        )
    except Exception:
        return None


def _data_protection_service(
    session: AsyncSession,
) -> DataProtectionService | None:
    settings = get_settings()
    if (
        not settings.DATA_PROTECTION_MASTER_KEYS.strip()
        and not settings.TENANT_CREDENTIAL_MASTER_KEY.strip()
    ):
        return None
    return DataProtectionService.from_settings(
        session,
        settings,
        master_key_unwrap=build_master_key_unwrap(settings),
        legacy_credential_key=settings.TENANT_CREDENTIAL_MASTER_KEY,
    )


def get_data_protection_service(
    session: AsyncSession = Depends(get_db_session),
) -> DataProtectionService:
    """Return the request-scoped data-protection service or fail closed."""

    try:
        service = _data_protection_service(session)
    except DataProtectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "data_protection_not_configured"},
        ) from exc
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "data_protection_not_configured"},
        )
    return service


def _tenant_credential_codec_or_503(settings: object) -> TenantCredentialCodec:
    try:
        return build_tenant_credential_encryptor_from_settings(settings)
    except TenantCredentialEncryptionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "tenant_credentials_not_configured"},
        ) from exc


def _maybe_tenant_credential_codec(settings: object) -> TenantCredentialCodec | None:
    try:
        return build_tenant_credential_encryptor_from_settings(settings)
    except TenantCredentialEncryptionError:
        return None


def _connector_scoped_credential_runtime(
    *,
    session: "AsyncSession",
    tenant_id: str,
    settings: object,
) -> ConnectorScopedCredentialRuntime | None:
    """Build a per-connector credential runtime for non-channel connectors.

    Returns None when the credential codec is unavailable so the caller
    falls back to channel-credential bridging gracefully.
    """
    codec = _maybe_tenant_credential_codec(settings)
    if codec is None:
        return None
    return ConnectorScopedCredentialRuntime(
        repository=ConnectorCredentialRepository(session),
        codec=codec,
        tenant_id=tenant_id,
    )


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
    return PostgresSessionPersistence(
        session,
        data_protection=_data_protection_service(session),
    )


def get_session_read_service(
    repo: SessionPersistenceProtocol = Depends(get_session_repository),
) -> SessionReadService:
    """Return the service boundary for read-only session runtime access."""
    return SessionReadService(session_runtime=SessionRuntime(persistence=repo))


def get_coordination_repository(
    session: AsyncSession = Depends(get_db_session),
) -> CoordinationPersistenceProtocol:
    """Return the Postgres coordination-persistence backend for this request."""
    return PostgresCoordinationPersistence(
        session,
        data_protection=_data_protection_service(session),
    )


def get_arbitration_repository(
    session: AsyncSession = Depends(get_db_session),
) -> ArbitrationPersistenceProtocol:
    """Return the Postgres arbitration-persistence backend for this request."""
    return PostgresArbitrationPersistence(session)


def get_boundary_repository(
    session: AsyncSession = Depends(get_db_session),
) -> BoundaryPersistenceProtocol:
    """Return the Postgres boundary-persistence backend for this request."""
    return PostgresBoundaryPersistence(
        session,
        data_protection=_data_protection_service(session),
    )


def get_resolution_proposal_repository(
    session: AsyncSession = Depends(get_db_session),
) -> PostgresResolutionProposalPersistence:
    """Return the Postgres resolution-proposal-persistence backend for this request."""
    return PostgresResolutionProposalPersistence(
        session,
        data_protection=_data_protection_service(session),
    )


def get_inbox_service(
    session_repo: SessionPersistenceProtocol = Depends(get_session_repository),
    resolution_repo: PostgresResolutionProposalPersistence = Depends(
        get_resolution_proposal_repository
    ),
) -> "InboxService":  # noqa: F821
    """Return the read-only inbox service for conversation thread views."""
    from app.services.inbox_service import InboxService

    return InboxService(
        session_repo=session_repo,
        resolution_repo=resolution_repo,
    )


def get_manager_assistant_service(
    session: AsyncSession = Depends(get_db_session),
) -> "ManagerAssistantService":  # noqa: F821
    """Return the Manager Assistant service for natural-language analytics queries."""
    from app.services.manager_assistant_service import (
        ManagerAssistantService,
        ManagerQueryRunner,
    )

    settings = get_settings()
    data_protection = _data_protection_service(session)
    tenant_config_repo = PostgresTenantConfigurationRepository(
        session,
        data_protection=data_protection,
    )
    try:
        llm_client = build_llm_client(settings)
    except Exception:
        llm_client = None  # type: ignore[assignment]

    from app.agents.governed.manager_assistant import ManagerAssistantAgent

    agent = ManagerAssistantAgent(
        llm_client=llm_client,
        tenant_configuration_repository=tenant_config_repo,
    ) if llm_client is not None else None  # type: ignore[assignment]

    runner = ManagerQueryRunner(
        observability_persistence=PostgresOperationalObservabilityPersistence(session),
        escalation_persistence=PostgresEscalationPersistence(session),
        case_approval_persistence=PostgresCaseApprovalPersistence(session),
        action_approval_persistence=PostgresActionApprovalRepository(session),
        session_persistence=PostgresSessionPersistence(
            session,
            data_protection=data_protection,
        ),
        tenant_config_repo=tenant_config_repo,
    )
    return ManagerAssistantService(agent=agent, query_runner=runner)  # type: ignore[arg-type]


def get_work_order_fulfillment_receipt_service(
    session: AsyncSession = Depends(get_db_session),
) -> WorkOrderFulfillmentReceiptService:
    """Return the receipt-only fulfillment callback service."""
    from app.services.work_order_fulfillment_receipt_service import (
        WorkOrderFulfillmentReceiptService,
    )

    return WorkOrderFulfillmentReceiptService(
        session=session,
        boundary_repository=PostgresBoundaryPersistence(
            session,
            data_protection=_data_protection_service(session),
        ),
        connector_config_repository=PostgresConnectorConfigRepository(session),
    )


def get_ticket_ingress_service(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> TicketIngressService:
    """Return the ticket-ingress write service for this request."""
    from app.boundary.ingress_dispatch_publisher import (
        enqueue_ingress_dispatch_outbox,
    )
    from app.boundary.whatsapp_media_fetch import (
        PostgresWhatsAppMediaFetchPersistence,
    )
    from app.boundary.whatsapp_media_fetch_publisher import (
        enqueue_whatsapp_media_fetch,
    )

    settings = get_settings()
    tenant_runtime: TenantConfigurationRuntime | None = None
    tenant_credential_codec = _maybe_tenant_credential_codec(settings)
    if tenant_credential_codec is not None:
        tenant_runtime = TenantConfigurationRuntime(
            repository=PostgresTenantConfigurationRepository(session),
            credential_encryptor=tenant_credential_codec,
        )
    session_factory = get_session_factory()
    admission_service = AdmissionService(
        gate=AdmissionGate(
            redis_client=cast(AdmissionRedisClient, get_redis_client()),
            thresholds=admission_thresholds_from_settings(settings),
            queue_depth_provider=get_queue_depth_provider(),
        ),
        session_factory=session_factory,
        db_pool_wait_provider=lambda: measure_db_pool_wait_ms(session_factory),
    )
    return TicketIngressService(
        persistence=PostgresBoundaryPersistence(
            session, data_protection=_data_protection_service(session)
        ),
        session=session,
        tenant_configuration_runtime=tenant_runtime,
        admission_service=admission_service,
        translation_runtime=cast(
            TranslationRuntime,
            request.app.state.translation_runtime,
        ),
        fingerprinter=cast(
            TextFingerprinter,
            getattr(
                request.app.state,
                "text_fingerprinter",
                TextFingerprinter(),
            ),
        ),
        circuit_breaker=cast(
            SemanticCircuitBreaker,
            request.app.state.semantic_circuit_breaker,
        ),
        circuit_event_repo=SemanticCircuitEventRepository(session),
        quarantine_service=QuarantineService(
            session,
            governance_repository=PostgresGovernanceRepository(session),
            publisher=CelerySemanticQuarantinePublisher(),
            event_runtime=OperationalEventAppender(
                persistence=PostgresOperationalEventPersistence(session)
            ),
        ),
        webhook_queue_by_channel={
            TenantChannelType.EMAIL: DIAGNOSTIC_QUEUE_PRIORITY,
            TenantChannelType.LARK: DIAGNOSTIC_QUEUE_PRIORITY,
            TenantChannelType.SHULEX: DIAGNOSTIC_QUEUE_PRIORITY,
            TenantChannelType.WHATSAPP: DIAGNOSTIC_QUEUE_PRIORITY,
        },
        ingress_dispatch_enqueue=enqueue_ingress_dispatch_outbox,
        ses_raw_email_fetcher=getattr(
            request.app.state, "ses_raw_email_fetcher", None
        ),
        attachment_blob_store=getattr(
            request.app.state, "attachment_blob_store", None
        ),
        whatsapp_media_fetch_repository=PostgresWhatsAppMediaFetchPersistence(
            session
        ),
        whatsapp_media_fetch_enqueue=enqueue_whatsapp_media_fetch,
    )


def get_whatsapp_customer_reply_send_service(
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppCustomerReplySendService:
    """Return the governed WhatsApp customer-reply send service."""

    settings = get_settings()
    tenant_credential_codec = _tenant_credential_codec_or_503(settings)
    data_protection = _data_protection_service(session)
    resolution_repository = PostgresResolutionProposalPersistence(
        session,
        data_protection=data_protection,
    )
    return WhatsAppCustomerReplySendService(
        draft_repository=resolution_repository,
        proposal_repository=resolution_repository,
        governance_repository=PostgresGovernanceRepository(session),
        tenant_runtime=TenantConfigurationRuntime(
            repository=PostgresTenantConfigurationRepository(session),
            credential_encryptor=tenant_credential_codec,
        ),
        delivery_repository=PostgresWhatsAppDeliveryRepository(session),
        sender=WhatsAppGraphSender(),
        session=session,
    )


def get_email_customer_reply_send_service(
    session: AsyncSession = Depends(get_db_session),
) -> EmailCustomerReplySendService:
    """Return the governed SES email customer-reply send service."""

    settings = get_settings()
    tenant_credential_codec = _tenant_credential_codec_or_503(settings)
    data_protection = _data_protection_service(session)
    resolution_repository = PostgresResolutionProposalPersistence(
        session,
        data_protection=data_protection,
    )
    return EmailCustomerReplySendService(
        draft_repository=resolution_repository,
        proposal_repository=resolution_repository,
        governance_repository=PostgresGovernanceRepository(session),
        tenant_runtime=TenantConfigurationRuntime(
            repository=PostgresTenantConfigurationRepository(session),
            credential_encryptor=tenant_credential_codec,
        ),
        delivery_repository=PostgresEmailDeliveryRepository(session),
        sender=SesV2EmailSender(),
        session=session,
    )


def get_quarantine_service(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> QuarantineService:
    """Return the semantic quarantine service for this request."""

    async def _ticket_reingest(
        *,
        external_id: str,
        channel: str,
        raw_content: str,
        language_code: str,
        expected_tenant_id: str,
        semantic_quarantine_enabled: bool,
    ) -> object:
        service = get_ticket_ingress_service(request=request, session=session)
        return await service.process(
            external_id=external_id,
            channel=cast(TicketChannel, channel),
            raw_content=raw_content,
            language_code=language_code,
            expected_tenant_id=expected_tenant_id,
            semantic_quarantine_enabled=semantic_quarantine_enabled,
        )

    return QuarantineService(
        session,
        governance_repository=PostgresGovernanceRepository(session),
        publisher=CelerySemanticQuarantinePublisher(),
        ticket_reingest=_ticket_reingest,
        event_runtime=OperationalEventAppender(
            persistence=PostgresOperationalEventPersistence(session)
        ),
    )


def get_semantic_circuit_service(
    session: AsyncSession = Depends(get_db_session),
) -> SemanticCircuitService:
    """Return the semantic circuit read service for this request."""

    return SemanticCircuitService(session)


def get_admission_service() -> AdmissionService:
    """Return the platform admission service for inbound workloads."""
    settings = get_settings()
    session_factory = get_session_factory()
    return AdmissionService(
        gate=AdmissionGate(
            redis_client=cast(AdmissionRedisClient, get_redis_client()),
            thresholds=admission_thresholds_from_settings(settings),
            queue_depth_provider=get_queue_depth_provider(),
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


def _case_approval_producer_dependencies(
    session: AsyncSession,
    *,
    data_protection: DataProtectionService | None,
) -> tuple[ApprovalQueueIngressService, CaseApprovalService]:
    governance_repository = PostgresGovernanceRepository(session)
    persistence = PostgresCaseApprovalPersistence(
        session,
        data_protection=data_protection,
    )
    return (
        ApprovalQueueIngressService(persistence=persistence),
        CaseApprovalService(
            persistence=persistence,
            sme_runtime=build_sme_review_runtime(),
            resolution_repository=PostgresResolutionProposalPersistence(
                session,
                data_protection=data_protection,
            ),
            governance_repository=governance_repository,
            session=None,
        ),
    )


async def get_conversation_service(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    execution_publisher: ExecutionPublisher = Depends(get_execution_publisher),
) -> AsyncIterator[ConversationService]:
    """Return the live conversation service for this request."""

    data_protection = _data_protection_service(session)
    approval_ingress, approval_reviewer = _case_approval_producer_dependencies(
        session,
        data_protection=data_protection,
    )
    execution_persistence = PostgresExecutionPersistence(session)
    execution_runtime = ExecutionRuntime(persistence=execution_persistence)
    deferred_execution_publisher = _DeferredExecutionPublisher(
        delegate=execution_publisher,
        execution_runtime=execution_runtime,
        session=session,
        publisher_id="api:conversation",
    )
    service = build_conversation_service(
        session_repository=PostgresSessionPersistence(
            session,
            data_protection=data_protection,
        ),
        # CoordinationRuntime is composed per request. There is no
        # app-state CoordinationPolicyRuntime singleton to invalidate;
        # each newly created service receives the current composition.
        coordination_runtime=CoordinationRuntime(
            governance_runtime=_dispatch_governance_runtime(
                PostgresGovernanceRepository(session)
            ),
            persistence=PostgresCoordinationPersistence(
                session,
                data_protection=data_protection,
            ),
            registry=_dispatch_coordination_registry(),
        ),
        execution_runtime=execution_runtime,
        execution_governance_runtime=ExecutionGovernanceRuntime(
            tenant_configuration_repository=PostgresTenantConfigurationRepository(
                session
            ),
            execution_persistence=execution_persistence,
            governance_repository=PostgresGovernanceRepository(session),
            provider_circuit_breaker=ProviderCircuitBreaker(session=session),
            default_provider_name="anthropic",
        ),
        execution_publisher=deferred_execution_publisher,
        redis_client=get_redis_client(),
        translation_runtime=cast(
            TranslationRuntime,
            request.app.state.translation_runtime,
        ),
        approval_queue_ingress=approval_ingress,
        case_approval_reviewer=approval_reviewer,
    )
    try:
        yield service
        await session.commit()
        await deferred_execution_publisher.flush()
    except Exception:
        await session.rollback()
        raise


async def get_dispatch_service(
    session: AsyncSession = Depends(get_db_session),
    execution_publisher: ExecutionPublisher = Depends(get_execution_publisher),
) -> AsyncIterator[DispatchService]:
    """Return the PR-W3 dispatch service for this request."""
    from app.boundary.whatsapp_media_fetch import (
        PostgresWhatsAppMediaFetchPersistence,
    )

    data_protection = _data_protection_service(session)
    approval_ingress, approval_reviewer = _case_approval_producer_dependencies(
        session,
        data_protection=data_protection,
    )
    execution_runtime = ExecutionRuntime(
        persistence=PostgresExecutionPersistence(session),
    )
    deferred_execution_publisher = _DeferredExecutionPublisher(
        delegate=execution_publisher,
        execution_runtime=execution_runtime,
        session=session,
        publisher_id="api:dispatch",
    )
    deferred_escalation_publisher = DeferredEscalationPublisher(
        delegate=CeleryEscalationPublisher(),
        escalation_runtime=EscalationAgentRuntime(
            escalation_persistence=PostgresEscalationPersistence(session),
            governance_repository=PostgresGovernanceRepository(session),
            session_persistence=PostgresSessionPersistence(
                session,
                data_protection=data_protection,
            ),
        ),
        session=session,
        publisher_id="api:dispatch",
    )
    tenant_topology_provider = TenantCoordinationTopologyRuntimeProvider(
        tenant_configuration_runtime=TenantConfigurationRuntime(
            repository=PostgresTenantConfigurationRepository(session),
        )
    )
    session_repository = PostgresSessionPersistence(
        session,
        data_protection=data_protection,
    )
    service = DispatchService(
        # Request-scoped coordination runtime: no cross-request policy
        # registry cache exists in the web process.
        coordination_runtime=CoordinationRuntime(
            governance_runtime=_dispatch_governance_runtime(
                PostgresGovernanceRepository(session)
            ),
            persistence=PostgresCoordinationPersistence(
                session,
                data_protection=data_protection,
            ),
            registry=_dispatch_coordination_registry(),
        ),
        boundary_ingress_repository=PostgresBoundaryPersistence(
            session,
            data_protection=data_protection,
        ),
        session_repository=session_repository,
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
        continuity_runtime=CaseContinuityRuntime(
            session_repository=session_repository,
        ),
        approval_queue_ingress=approval_ingress,
        case_approval_reviewer=approval_reviewer,
        whatsapp_media_fetch_repository=PostgresWhatsAppMediaFetchPersistence(
            session
        ),
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
    boundary_repository: BoundaryPersistenceProtocol = Depends(get_boundary_repository),
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


def get_supervisor_inbox_service(
    session: AsyncSession = Depends(get_db_session),
) -> SupervisorInboxService:
    """Return the supervisor inbox read service for this request."""
    return SupervisorInboxService(
        supervisor_repository=PostgresSupervisorRepository(session),
        qa_persistence=PostgresQAPersistence(session),
        training_repository=PostgresTrainingRecommendationRepository(session),
    )


def get_trainer_recommendation_service(
    session: AsyncSession = Depends(get_db_session),
) -> TrainerRecommendationService:
    """Return the trainer recommendation service for this request."""
    return TrainerRecommendationService(
        repository=PostgresTrainingRecommendationRepository(session),
        session=session,
    )


def get_escalation_service(
    session: AsyncSession = Depends(get_db_session),
) -> EscalationService:
    """Return the Command Center escalation service for this request."""
    data_protection = _data_protection_service(session)
    return EscalationService(
        runtime=EscalationAgentRuntime(
            escalation_persistence=PostgresEscalationPersistence(session),
            governance_repository=PostgresGovernanceRepository(session),
            session_persistence=PostgresSessionPersistence(
                session,
                data_protection=data_protection,
            ),
        ),
        session=session,
    )


def get_tenant_configuration_service(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> TenantConfigurationService:
    """Return the tenant-owned configuration service for this request."""
    settings = get_settings()
    data_protection = _data_protection_service(session)
    runtime = TenantConfigurationRuntime(
        repository=PostgresTenantConfigurationRepository(
            session,
            data_protection=data_protection,
        ),
        credential_encryptor=_tenant_credential_codec_or_503(settings),
    )
    return TenantConfigurationService(
        runtime=runtime,
        session=session,
        redis_client=getattr(request.app.state, "redis_client", get_redis_client()),
    )


def get_tenant_config_change_request_service(
    session: AsyncSession = Depends(get_db_session),
    tenant_configuration_service: TenantConfigurationService = Depends(
        get_tenant_configuration_service
    ),
) -> TenantConfigChangeRequestService:
    """Return the durable tenant config dual-control ledger service."""
    settings = get_settings()
    codec = _maybe_tenant_credential_codec(settings)
    return TenantConfigChangeRequestService(
        repository=PostgresTenantConfigChangeRequestRepository(session),
        tenant_configuration_service=tenant_configuration_service,
        event_appender=OperationalEventAppender(
            persistence=PostgresOperationalEventPersistence(session)
        ),
        session=session,
        knowledge_reindex_publisher=CeleryKnowledgeReindexPublisher(),
        connector_credential_repository=ConnectorCredentialRepository(session),
        connector_credential_codec=codec,
    )


def get_tenant_lifecycle_service(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> TenantLifecycleService:
    """Return the platform-gated tenant lifecycle service."""
    return TenantLifecycleService(
        repository=PostgresTenantLifecycleRepository(session),
        event_appender=OperationalEventAppender(
            persistence=PostgresOperationalEventPersistence(session)
        ),
        session=session,
        auth0_management_client=cast(
            Auth0ManagementClientProtocol | None,
            getattr(request.app.state, "auth0_management_client", None),
        ),
    )


def get_cognition_service(
    session: AsyncSession = Depends(get_db_session),
) -> CognitionService:
    """Return the Cognition Hub lifecycle service for this request."""
    settings = get_settings()
    data_protection = _data_protection_service(session)
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
                PostgresTenantConfigurationRepository(
                    session,
                    data_protection=data_protection,
                )
            ),
        ),
        usage_persistence=PostgresCognitionUsagePersistence(
            session,
            audit_encryptor=audit_encryptor,
            data_protection=data_protection,
        ),
        approval_event_projector=PostgresSOPApprovalApplyEventProjector(
            session=session
        ),
        knowledge_reindex_publisher=CeleryKnowledgeReindexPublisher(),
        session=session,
    )


def get_action_approval_service(
    session: AsyncSession = Depends(get_db_session),
) -> ActionApprovalService:
    """Return the manager action-approval service for this request."""
    return build_action_approval_service(session)


def build_action_approval_service(
    session: AsyncSession,
) -> ActionApprovalService:
    """Construct the manager action-approval service for a session."""
    settings = get_settings()
    data_protection = _data_protection_service(session)
    governance_repository = PostgresGovernanceRepository(session)
    session_repository = PostgresSessionPersistence(
        session,
        data_protection=data_protection,
    )
    timeline_runtime = TimelineRuntime(persistence=session_repository)
    deferred_escalation_publisher = DeferredEscalationPublisher(
        delegate=CeleryEscalationPublisher(),
        escalation_runtime=EscalationAgentRuntime(
            escalation_persistence=PostgresEscalationPersistence(session),
            governance_repository=governance_repository,
            session_persistence=session_repository,
        ),
        session=session,
        publisher_id="api:action-approval",
    )

    # One manager decision on a case-bound action must do both halves or
    # neither: if approving/denying THIS action also resolves a linked
    # case_approval_records row, deliver its reply (when approved) in the
    # SAME transaction -- the standalone Action Approvals surface must
    # never be able to fire a case-bound action while leaving its reply
    # undelivered. Full parity with get_case_approval_service's wiring
    # (including the governance gate -- see case_approval_recovery_tasks
    # for why it's required, not optional, for these cases).
    case_completion_service = CaseApprovalService(
        persistence=PostgresCaseApprovalPersistence(
            session, data_protection=data_protection
        ),
        sme_runtime=build_sme_review_runtime(),
        resolution_repository=PostgresResolutionProposalPersistence(
            session, data_protection=data_protection
        ),
        governance_repository=governance_repository,
        resolution_governance_gate=ResolutionGovernanceGate(
            governance_runtime=build_resolution_governance_runtime(
                persistence=governance_repository,
                grounding_checker=CitationCoverageGroundingChecker(
                    document_repository=PostgresTenantConfigurationRepository(
                        session, data_protection=data_protection
                    ),
                ),
            )
        ),
        session=session,
        coordination_repository=PostgresCoordinationPersistence(
            session, data_protection=data_protection
        ),
        outbound_auto_send_service=OutboundAutoSendService(
            governance_repository=governance_repository,
            outbox_persistence=PostgresOutboundSendOutboxPersistence(session),
        ),
    )

    async def _complete_case_for_action(
        action_approval_id: str,
        tenant_id: str,
        action_status: str,
        resolved_by: str,
        resolved_at: datetime,
        resolution_note: str,
    ) -> object:
        return await case_completion_service.claim_and_complete_case_for_action(
            action_approval_id=action_approval_id,
            tenant_id=tenant_id,
            action_status=action_status,
            resolved_by=resolved_by,
            resolved_at=resolved_at,
            resolution_note=resolution_note,
        )

    async def _orchestration_factory(tenant_id: str) -> ActionOrchestrationRuntime:
        approval_ingress, approval_reviewer = _case_approval_producer_dependencies(
            session,
            data_protection=data_protection,
        )
        tenant_runtime = TenantConfigurationRuntime(
            repository=PostgresTenantConfigurationRepository(
                session,
                data_protection=data_protection,
            ),
            credential_encryptor=_tenant_credential_codec_or_503(settings),
        )
        return ActionOrchestrationRuntime(
            tool_invoker=ToolInvoker(
                tool_registry=await build_tenant_action_tool_registry(
                    tenant_id=tenant_id,
                    config_repository=PostgresConnectorConfigRepository(session),
                    credential_runtime=tenant_runtime,
                    connector_credential_runtime=_connector_scoped_credential_runtime(
                        session=session,
                        tenant_id=tenant_id,
                        settings=settings,
                    ),
                    work_order_repository=PostgresWorkOrderRepository(session),
                    allow_stub_actions=settings.allow_stub_actions_effective,
                ),
                governance_runtime=build_action_tool_governance_runtime(
                    persistence=governance_repository,
                    redis_client=get_redis_client(),
                    tenant_configuration_repository=(
                        PostgresTenantConfigurationRepository(
                            session,
                            data_protection=data_protection,
                        )
                    ),
                ),
                grant_repository=PostgresAgentActionGrantRepository(session),
                connector_invocation_repository=(
                    PostgresConnectorInvocationRepository(session)
                ),
                escalation_publisher=deferred_escalation_publisher,
                redis_client=get_redis_client(),
                pre_approved_decision_ttl_seconds=(
                    settings.AGENT_PRE_APPROVED_DECISION_TTL_SECONDS
                ),
            ),
            approval_repository=PostgresActionApprovalRepository(session),
            timeline_runtime=timeline_runtime,
            approval_queue_ingress=approval_ingress,
            case_approval_reviewer=approval_reviewer,
        )

    return ActionApprovalService(
        approval_repository=PostgresActionApprovalRepository(session),
        grant_repository=PostgresAgentActionGrantRepository(session),
        governance_repository=governance_repository,
        resolution_repository=PostgresResolutionProposalPersistence(
            session,
            data_protection=data_protection,
        ),
        session_repository=session_repository,
        orchestration_runtime_factory=_orchestration_factory,
        timeline_runtime=timeline_runtime,
        session=session,
        post_commit_flush=deferred_escalation_publisher.flush,
        case_resolution_completer=_complete_case_for_action,
    )


def get_case_approval_service(
    session: AsyncSession = Depends(get_db_session),
) -> CaseApprovalService:
    """Return the SME-reviewed case approval service."""
    data_protection = _data_protection_service(session)
    governance_repository = PostgresGovernanceRepository(session)

    # Share the request session with the action-approval service so that a
    # case approval that fires a bound action commits the case-approved row
    # and the fired side-effect atomically (single commit owned here).
    action_service = build_action_approval_service(session)

    async def _approve_bound_action(
        approval_id: str,
        approved_by: str,
        note: str | None,
        tenant_id: str,
        expected_tenant_id: str,
    ) -> object:
        return await action_service.approve_in_transaction(
            approval_id=approval_id,
            approved_by=approved_by,
            note=note,
            tenant_id=tenant_id,
            expected_tenant_id=expected_tenant_id,
        )

    async def _deny_bound_action(
        approval_id: str,
        denied_by: str,
        reason: str,
        tenant_id: str,
        expected_tenant_id: str,
    ) -> object:
        return await action_service.deny_in_transaction(
            approval_id=approval_id,
            denied_by=denied_by,
            reason=reason,
            tenant_id=tenant_id,
            expected_tenant_id=expected_tenant_id,
        )

    return CaseApprovalService(
        persistence=PostgresCaseApprovalPersistence(
            session,
            data_protection=data_protection,
        ),
        sme_runtime=build_sme_review_runtime(),
        resolution_repository=PostgresResolutionProposalPersistence(
            session,
            data_protection=data_protection,
        ),
        governance_repository=governance_repository,
        escalation_runtime=EscalationAgentRuntime(
            escalation_persistence=PostgresEscalationPersistence(session),
            governance_repository=governance_repository,
            session_persistence=PostgresSessionPersistence(
                session,
                data_protection=data_protection,
            ),
        ),
        action_approval_approve=_approve_bound_action,
        action_approval_deny=_deny_bound_action,
        post_commit_flush=action_service.flush_after_commit,
        resolution_governance_gate=ResolutionGovernanceGate(
            governance_runtime=build_resolution_governance_runtime(
                persistence=governance_repository,
                grounding_checker=CitationCoverageGroundingChecker(
                    document_repository=PostgresTenantConfigurationRepository(
                        session,
                        data_protection=data_protection,
                    ),
                ),
            ),
        ),
        session=session,
        coordination_repository=PostgresCoordinationPersistence(
            session,
            data_protection=data_protection,
        ),
        outbound_auto_send_service=OutboundAutoSendService(
            governance_repository=governance_repository,
            outbox_persistence=PostgresOutboundSendOutboxPersistence(session),
        ),
    )


def get_approval_queue_ingress_service(
    session: AsyncSession = Depends(get_db_session),
) -> ApprovalQueueIngressService:
    """Return the producer-facing approval queue ingress boundary."""
    data_protection = _data_protection_service(session)
    return ApprovalQueueIngressService(
        persistence=PostgresCaseApprovalPersistence(
            session,
            data_protection=data_protection,
        ),
        publisher=CeleryCaseApprovalReviewPublisher(),
    )


def get_crisis_service(
    session: AsyncSession = Depends(get_db_session),
) -> CrisisService:
    """Return the tenant crisis-mode service for this request."""

    return CrisisService(
        session=session,
        redis_client=get_redis_client(),
        event_repository=PostgresCrisisEventRepository(session),
        event_runtime=OperationalEventAppender(
            persistence=PostgresOperationalEventPersistence(session)
        ),
    )


def get_knowledge_service(
    session: AsyncSession = Depends(get_db_session),
) -> KnowledgeService:
    """Return the tenant knowledge ingestion/retrieval service."""
    settings = get_settings()
    data_protection = _data_protection_service(session)
    tenant_config_repo = PostgresTenantConfigurationRepository(
        session,
        data_protection=data_protection,
    )
    runtime = KnowledgeRuntime(
        repository=PostgresKnowledgeRepository(
            session,
            data_protection=data_protection,
        ),
        tenant_configuration_repository=tenant_config_repo,
        embedding_provider=build_embedding_provider(settings),
        chunker=DeterministicKnowledgeChunker(
            target_size=settings.CHUNK_TARGET_SIZE,
            overlap=settings.CHUNK_OVERLAP,
            min_size=settings.CHUNK_MIN_SIZE,
        ),
        vector_index_name=settings.VECTOR_DEFAULT_INDEX,
        default_context_token_budget=settings.RAG_DEFAULT_CONTEXT_TOKEN_BUDGET,
        sop_contradiction_agent=_build_sop_contradiction_agent(session, settings),
    )
    contradiction_agent = _build_sop_contradiction_agent(session, settings)
    return KnowledgeService(
        runtime=runtime,
        session=session,
        tenant_configuration_repository=tenant_config_repo,
        sop_contradiction_agent=contradiction_agent,
    )


def get_sop_intelligence_service(
    session: AsyncSession = Depends(get_db_session),
) -> SOPIntelligenceService:
    """Return the SOP intelligence proposal service for this request."""
    data_protection = _data_protection_service(session)
    return SOPIntelligenceService(
        runtime=SOPIntelligenceRuntime(
            approval_persistence=PostgresSOPApprovalPersistence(session),
            session_persistence=PostgresSessionPersistence(
                session,
                data_protection=data_protection,
            ),
            supervisor_repository=PostgresSupervisorRepository(session),
            qa_persistence=PostgresQAPersistence(session),
            governance_repository=PostgresGovernanceRepository(session),
            tenant_configuration_repository=(
                PostgresTenantConfigurationRepository(
                    session,
                    data_protection=data_protection,
                )
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
        boundary_persistence=PostgresBoundaryPersistence(
            session, data_protection=_data_protection_service(session)
        ),
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

    return QueueOperationsService(
        session=session,
        queue_depth_provider_factory=get_queue_depth_provider,
    )


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
    outbox_id: str
    claim_id: str


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
        claim = await self._execution_runtime.claim_outbox_for_execution(
            execution_id=execution_id,
            publisher_id=self._publisher_id,
        )
        if not claim.claimed or claim.outbox is None:
            if claim.reason == "outbox_not_publishable:published":
                return
            raise ExecutionOutboxPublishError(
                execution_id,
                claim.reason or "outbox_claim_refused",
            )
        claim_id = _require_execution_outbox_claim_id(claim.outbox.claim_id)
        if isinstance(self._delegate, QueueBackpressureCheck):
            try:
                await self._delegate.check_backpressure(tenant_id=tenant_id)
            except Exception as exc:
                await self._execution_runtime.mark_outbox_failed(
                    outbox_id=str(claim.outbox.outbox_id),
                    claim_id=str(claim_id),
                    error=_bounded_publish_error(exc),
                )
                await self._session.commit()
                raise
        self._diagnostic_executions.append(
            _DiagnosticExecutionIntent(
                execution_id=execution_id,
                tenant_id=tenant_id,
                outbox_id=str(claim.outbox.outbox_id),
                claim_id=str(claim_id),
            )
        )

    async def flush(self) -> None:
        for intent in self._diagnostic_executions:
            await self._session.commit()
            try:
                await self._delegate.publish_execution(
                    execution_id=intent.execution_id,
                    tenant_id=intent.tenant_id,
                )
            except Exception as exc:
                await self._execution_runtime.mark_outbox_failed(
                    outbox_id=intent.outbox_id,
                    claim_id=intent.claim_id,
                    error=_bounded_publish_error(exc),
                )
                await self._session.commit()
                raise ExecutionOutboxPublishError(
                    intent.execution_id,
                    _bounded_publish_error(exc),
                ) from exc
            published = await self._execution_runtime.mark_outbox_published(
                outbox_id=intent.outbox_id,
                claim_id=intent.claim_id,
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


def _bounded_publish_error(exc: BaseException) -> str:
    message = f"{exc.__class__.__name__}: {exc}"
    if len(message) > 240:
        return f"{message[:237]}..."
    return message


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
    "get_conversation_service",
    "get_coordination_repository",
    "get_data_protection_service",
    "get_email_customer_reply_send_service",
    "get_escalation_service",
    "get_governance_repository",
    "get_health_service",
    "get_knowledge_service",
    "get_operational_event_service",
    "get_operational_observability_service",
    "get_queue_operations_service",
    "get_quarantine_service",
    "get_inbox_service",
    "get_manager_assistant_service",
    "get_quota_operations_service",
    "get_quota_runtime",
    "get_resolution_proposal_repository",
    "get_semantic_circuit_service",
    "get_session_read_service",
    "get_session_repository",
    "get_sop_intelligence_service",
    "get_supervisor_repository",
    "get_tenant_config_change_request_service",
    "get_tenant_configuration_service",
    "get_tenant_lifecycle_service",
    "get_whatsapp_customer_reply_send_service",
]

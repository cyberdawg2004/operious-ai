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

from dataclasses import dataclass
from collections.abc import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

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
from app.core.config import get_settings
from app.core.redis import get_redis_client
from app.dependencies.database import get_db_session, get_session_factory
from app.execution.celery_publisher import CeleryExecutionPublisher
from app.execution.publisher import ExecutionPublisher
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
from app.services.dispatch_service import (
    DispatchCommunicationPolicy,
    DispatchService,
)
from app.services.health_service import HealthService
from app.services.ticket_ingress_service import TicketIngressService
from app.session.persistence import (
    PostgresSessionPersistence,
    SessionPersistenceProtocol,
)
from app.supervisor.persistence import (
    BaseSupervisorRepository,
    PostgresSupervisorRepository,
)


async def get_health_service() -> HealthService:
    """Construct `HealthService` with lazy readiness collaborators."""
    return HealthService(
        settings=get_settings(),
        session_factory_provider=get_session_factory,
        redis_provider=get_redis_client,
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
    return TicketIngressService(
        persistence=PostgresBoundaryPersistence(session),
        session=session,
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
    deferred_execution_publisher = _DeferredExecutionPublisher(
        execution_publisher
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
        execution_publisher=deferred_execution_publisher,
    )
    try:
        yield service
        await session.commit()
        await deferred_execution_publisher.flush()
    except Exception:
        await session.rollback()
        raise


def get_supervisor_repository(
    session: AsyncSession = Depends(get_db_session),
) -> BaseSupervisorRepository:
    """Return the Postgres supervisor-persistence backend for this request."""
    return PostgresSupervisorRepository(session)


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
    dispatch_id: str
    session_id: str
    tenant_id: str


class _DeferredExecutionPublisher(ExecutionPublisher):
    """Request-scoped publisher that flushes after DB commit."""

    def __init__(self, delegate: ExecutionPublisher) -> None:
        self._delegate = delegate
        self._diagnostic_executions: list[_DiagnosticExecutionIntent] = []

    async def publish_diagnostic_execution(
        self,
        dispatch_id: str,
        session_id: str,
        tenant_id: str,
    ) -> None:
        self._diagnostic_executions.append(
            _DiagnosticExecutionIntent(
                dispatch_id=dispatch_id,
                session_id=session_id,
                tenant_id=tenant_id,
            )
        )

    async def flush(self) -> None:
        for intent in self._diagnostic_executions:
            await self._delegate.publish_diagnostic_execution(
                dispatch_id=intent.dispatch_id,
                session_id=intent.session_id,
                tenant_id=intent.tenant_id,
            )


__all__ = [
    "get_arbitration_repository",
    "get_boundary_repository",
    "get_coordination_repository",
    "get_governance_repository",
    "get_health_service",
    "get_session_repository",
    "get_supervisor_repository",
]

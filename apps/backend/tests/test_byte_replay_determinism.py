"""Byte replay proof for runtime-generated lineage identities."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import ClassVar, FrozenSet

import pytest

from app.boundary.adapters.base import BaseIngressAdapter
from app.boundary.contracts.requests import BoundaryIngressRequest
from app.boundary.enums import (
    BoundaryMessageType,
    BoundaryNormalizationStatus,
    BoundarySourceType,
)
from app.boundary.ingress import BoundaryIngressRuntime
from app.boundary.models.normalization import BoundaryNormalizationResult
from app.boundary.models.payload import IngressPayload
from app.boundary.models.source import BoundarySource
from app.boundary.persistence import InMemoryBoundaryPersistence
from app.boundary.registry import BoundaryAdapterRegistry
from app.coordination.contracts import CoordinationDispatchRequest, CoordinationMessage
from app.coordination.enums import (
    CoordinationDirection,
    CoordinationMessageType,
    CoordinationPriority,
)
from app.coordination.identity import derive_correlation_id, derive_message_id
from app.coordination.models.participants import CoordinationParticipant
from app.coordination.models.payload import CoordinationPayload
from app.coordination.models.recipients import CoordinationRecipient
from app.coordination.persistence import InMemoryCoordinationPersistence
from app.coordination.registry import CoordinationRegistry
from app.coordination.runtime import CoordinationRuntime
from app.execution import ExecutionRuntime, InMemoryExecutionPersistence
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
from app.governance.persistence import InMemoryGovernanceRepository
from app.governance.policies.base import BaseGovernancePolicy
from app.governance.policies.chain import PolicyChain
from app.governance.subjects.base import SubjectKind
from app.governance.subjects.communication import CommunicationGovernanceSubject
from app.identity import AuthorityContext
from app.session.contracts.requests import OpenSessionRequest
from app.session.contracts.results import OpenSessionResult
from app.session.enums import SessionScope
from app.session.persistence import InMemorySessionPersistence
from app.session.runtime import SessionRuntime
from tests.conftest import execution_admission_token

TENANT_ID = "tenant-byte-replay"
PRINCIPAL_ID = "principal-byte-replay"
REQUEST_ID = "req-byte-replay"
EXTERNAL_MESSAGE_ID = "ticket-byte-replay-001"
NOW = datetime(2026, 5, 22, 18, 0, tzinfo=timezone.utc)


class _ReplayIngressAdapter(BaseIngressAdapter):
    def __init__(self) -> None:
        super().__init__(name="byte_replay_adapter", source_type=BoundarySourceType.EMAIL)

    def normalize(
        self,
        *,
        source: BoundarySource,
        payload: IngressPayload,
    ) -> BoundaryNormalizationResult:
        body = payload.body
        assert isinstance(body, Mapping)
        return BoundaryNormalizationResult(
            status=BoundaryNormalizationStatus.OK,
            message_type=BoundaryMessageType.MESSAGE_RECEIVED,
            external_message_id=str(body["external_message_id"]),
            external_conversation_id="conversation-byte-replay",
            external_emitted_at=NOW,
            canonical_payload={
                "subject": str(body["subject"]),
                "body": str(body["body"]),
            },
        )


class _AllowCommunicationPolicy(BaseGovernancePolicy):
    name: ClassVar[str] = "byte_replay.dispatch.allow"
    supported_stages: ClassVar[FrozenSet[EnforcementStage]] = frozenset(
        {EnforcementStage.PRE_EXECUTION}
    )
    applicable_subject_kinds: ClassVar[FrozenSet[SubjectKind]] = frozenset(
        {SubjectKind.COMMUNICATION}
    )

    async def evaluate(
        self,
        context: GovernanceContext,
    ) -> Sequence[PolicyEvaluationResult]:
        assert isinstance(context.subject, CommunicationGovernanceSubject)
        return (
            PolicyEvaluationResult(
                policy_name=self.name,
                rule_id="allow",
                decision=Decision.ALLOW,
                severity=ViolationSeverity.LOW,
                reason="byte replay allowed",
                evaluated_at=NOW,
            ),
        )


def _governance_runtime(repository: InMemoryGovernanceRepository) -> GovernanceRuntime:
    handlers = EnforcementHandlerRegistry()
    for handler in (
        AllowHandler(),
        DenyHandler(),
        RedactHandler(),
        DegradeHandler(),
        EscalateHandler(),
        RequireApprovalHandler(),
    ):
        handlers.register(handler)
    return GovernanceRuntime(
        engine=PolicyEvaluationEngine(),
        handler_registry=handlers,
        chains={
            EnforcementStage.PRE_EXECUTION: PolicyChain(
                chain_id="byte_replay.pre_execution",
                stage=EnforcementStage.PRE_EXECUTION,
                policies=(_AllowCommunicationPolicy(),),
            )
        },
        persistence=repository,
    )


def _coordination_registry() -> CoordinationRegistry:
    registry = CoordinationRegistry()
    registry.register(
        CoordinationParticipant(participant_id="runtime:boundary-ingress", kind="runtime")
    )
    registry.register(
        CoordinationParticipant(participant_id="agent:ticket-triage", kind="agent")
    )
    return registry


async def _run_lineage_once() -> dict[str, str]:
    boundary_store = InMemoryBoundaryPersistence()
    governance_store = InMemoryGovernanceRepository()
    coordination_store = InMemoryCoordinationPersistence()
    session_store = InMemorySessionPersistence()
    execution_store = InMemoryExecutionPersistence()
    authority = AuthorityContext.from_raw(
        tenant_id=TENANT_ID,
        principal_id=PRINCIPAL_ID,
    )

    boundary_runtime = BoundaryIngressRuntime(
        adapters=BoundaryAdapterRegistry((_ReplayIngressAdapter(),)),
        persistence=boundary_store,
    )
    ingress = (
        await boundary_runtime.ingest(
            BoundaryIngressRequest(
                source=BoundarySource(
                    source_type=BoundarySourceType.EMAIL,
                    source_id="support-inbox",
                    tenant_id=TENANT_ID,
                ),
                adapter_name="byte_replay_adapter",
                payload=IngressPayload(
                    body={
                        "external_message_id": EXTERNAL_MESSAGE_ID,
                        "subject": "Replay me",
                        "body": "Same bytes should produce same lineage.",
                    },
                    content_type="application/json",
                ),
                correlation_id="corr-byte-replay",
                request_id=REQUEST_ID,
                authority=authority,
            )
        )
    ).unwrap()
    assert ingress.event_id is not None
    assert ingress.replay_key is not None

    coordination_runtime = CoordinationRuntime(
        governance_runtime=_governance_runtime(governance_store),
        persistence=coordination_store,
        registry=_coordination_registry(),
    )
    coordination = await coordination_runtime.dispatch(
        CoordinationDispatchRequest(
            message=CoordinationMessage(
                message_id=derive_message_id(
                    seed=f"boundary:{ingress.ingress_id}:message"
                ),
                message_type=CoordinationMessageType.REQUEST,
                sender_id="runtime:boundary-ingress",
                recipient=CoordinationRecipient(
                    recipient_id="agent:ticket-triage",
                    kind="agent",
                    tenant_id=TENANT_ID,
                ),
                payload=CoordinationPayload(
                    content_type="operious/boundary-ingress",
                    schema_version="1",
                    body={
                        "ingress_id": str(ingress.ingress_id),
                        "event_id": str(ingress.event_id),
                        "replay_key": str(ingress.replay_key),
                    },
                ),
                priority=CoordinationPriority.NORMAL,
            ),
            direction=CoordinationDirection.RUNTIME_TO_AGENT,
            correlation_id=derive_correlation_id(seed=f"boundary:{ingress.ingress_id}"),
            request_id=REQUEST_ID,
            tenant_id=TENANT_ID,
            authority=authority,
        )
    )
    assert coordination.is_ok, coordination.error
    assert coordination.envelope is not None
    assert coordination.trace.governance_decision_id is not None

    session_runtime = SessionRuntime(persistence=session_store)
    session_envelope = await session_runtime.open_session(
        OpenSessionRequest(
            scope=SessionScope.TENANT,
            external_handle=str(ingress.ingress_id),
            tenant_id=TENANT_ID,
            principal_id=PRINCIPAL_ID,
            opened_at_override=NOW + timedelta(seconds=3),
            correlation_id=str(coordination.envelope.correlation_id),
            request_id=REQUEST_ID,
            authority=authority,
        )
    )
    assert session_envelope.is_ok, session_envelope.trace.error
    assert isinstance(session_envelope.result, OpenSessionResult)
    session = session_envelope.result.session
    assert session is not None

    execution_runtime = ExecutionRuntime(persistence=execution_store)
    execution_request = await execution_runtime.request_diagnostic_execution(
        dispatch_id=str(coordination.coordination_id),
        session_id=str(session.identity.session_id),
        tenant_id=TENANT_ID,
        requested_at=NOW + timedelta(seconds=4),
        admission_token=execution_admission_token(
            tenant_id=TENANT_ID,
            admitted_at=NOW + timedelta(seconds=4),
            seed="byte-replay",
        ),
    )
    claim = await execution_runtime.claim_execution(
        execution_id=execution_request.execution.execution_id,
        worker_id="worker:byte-replay",
        claimed_at=NOW + timedelta(seconds=5),
    )
    assert claim.claimed
    assert claim.attempt is not None
    outbox = await execution_runtime.get_outbox_by_execution(
        execution_request.execution.execution_id
    )
    assert outbox is not None

    lineage = {
        "boundary_ingress": str(ingress.ingress_id),
        "boundary_event": str(ingress.event_id),
        "boundary_replay_key": str(ingress.replay_key),
        "coordination_id": str(coordination.coordination_id),
        "coordination_message": str(coordination.envelope.message.message_id),
        "coordination_correlation": str(coordination.envelope.correlation_id),
        "governance_decision": str(coordination.trace.governance_decision_id),
        "session_id": str(session.identity.session_id),
        "execution_id": str(execution_request.execution.execution_id),
        "execution_outbox": str(outbox.outbox_id),
        "execution_attempt": str(claim.attempt.attempt_id),
    }
    lineage["lineage_sha256"] = hashlib.sha256(
        json.dumps(lineage, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return lineage


@pytest.mark.asyncio
async def test_identical_ingress_produces_identical_lineage() -> None:
    first = await _run_lineage_once()
    second = await _run_lineage_once()

    assert first == second

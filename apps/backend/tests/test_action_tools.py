"""RT6 governed action tools and approval records."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, ClassVar, FrozenSet, Sequence

import pytest

from app.agents.capabilities import (
    AgentCapability,
    CapabilitySet,
    ExecutionConstraints,
)
from app.agents.context import AgentExecutionContext
from app.agents.enums import CapabilityScope
from app.agents.exceptions import ToolConfigurationError
from app.agents.identity import AgentIdentity, ExecutionIdentity
from app.agents.results import ToolInvocationRequest, ToolInvocationResult
from app.agents.tools import ToolInvoker, ToolRegistry
from app.agents.tools.actions import (
    RefundRequestTool,
    WarrantyClaimTool,
)
from app.agents.tools.approvals import (
    InMemoryActionApprovalRepository,
    PostgresActionApprovalRepository,
    build_pending_action_approval,
)
from app.agents.tools.orchestration import ActionOrchestrationRuntime
from app.agents.value_objects import CausalityMetadata
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
from app.governance.enums import Decision, EnforcementStage
from app.governance.evaluators.engine import PolicyEvaluationEngine
from app.governance.persistence.memory import InMemoryGovernanceRepository
from app.governance.policies.base import BaseGovernancePolicy
from app.governance.policies.chain import PolicyChain
from app.governance.subjects.base import SubjectKind
from app.resolution.enums import (
    ResolutionAutonomyDecision,
    ResolutionGovernanceVerdict,
    ResolutionProposalStatus,
    ResolutionSupervisorVerdict,
)
from app.resolution.identity import ResolutionProposalId
from app.resolution.persistence.records import ResolutionProposalRecord
from tests.conftest import requires_postgres, set_pg_rls_tenant

TENANT_ID = "tenant-action"
SESSION_ID = "11111111-1111-4111-8111-111111111111"
EXECUTION_ID = "22222222-2222-4222-8222-222222222222"
DISPATCH_ID = "33333333-3333-4333-8333-333333333333"
TARGET_RESOURCE = "order:order-1:sku:A123"


class _DecisionPolicy(BaseGovernancePolicy):
    name: ClassVar[str] = "rt6_action_tool_gate"
    supported_stages: ClassVar[FrozenSet[EnforcementStage]] = frozenset(
        {EnforcementStage.PRE_EXECUTION}
    )
    applicable_subject_kinds: ClassVar[FrozenSet[SubjectKind]] = frozenset(
        {SubjectKind.AGENT_ACTION}
    )

    def __init__(self, decision: Decision) -> None:
        self._decision = decision

    async def evaluate(
        self, context: GovernanceContext
    ) -> Sequence[PolicyEvaluationResult]:
        return (
            PolicyEvaluationResult(
                policy_name=self.name,
                rule_id=f"action_tool_{self._decision.value}",
                decision=self._decision,
                reason=f"fixture returned {self._decision.value}",
            ),
        )


class _CountingWarrantyClaimTool(WarrantyClaimTool):
    def __init__(self, calls: list[dict[str, object]]) -> None:
        self._calls = calls

    async def invoke(
        self,
        request: ToolInvocationRequest,
        context: AgentExecutionContext,
    ) -> ToolInvocationResult:
        self._calls.append(dict(request.payload))
        return await super().invoke(request, context)


class _Timeline:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    async def append_event(
        self,
        *,
        session_id: str,
        dispatch_id: str,
        tenant_id: str,
        event_type: str,
        payload: dict[str, object] | None = None,
        timestamp: datetime | None = None,
        idempotency_key: str | None = None,
    ) -> object:
        self.events.append(
            {
                "session_id": session_id,
                "dispatch_id": dispatch_id,
                "tenant_id": tenant_id,
                "event_type": event_type,
                "payload": dict(payload or {}),
                "timestamp": timestamp,
                "idempotency_key": idempotency_key,
            }
        )
        return object()


def _handlers() -> EnforcementHandlerRegistry:
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


def _governance(
    decision: Decision,
) -> tuple[GovernanceRuntime, InMemoryGovernanceRepository]:
    persistence = InMemoryGovernanceRepository()
    chain = PolicyChain(
        chain_id="rt6.action.tools.pre_execution",
        stage=EnforcementStage.PRE_EXECUTION,
        policies=(_DecisionPolicy(decision),),
    )
    return (
        GovernanceRuntime(
            engine=PolicyEvaluationEngine(),
            handler_registry=_handlers(),
            chains={EnforcementStage.PRE_EXECUTION: chain},
            persistence=persistence,
        ),
        persistence,
    )


def _registry(tool: WarrantyClaimTool | RefundRequestTool) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(tool)
    return registry


def _context() -> AgentExecutionContext:
    return AgentExecutionContext(
        identity=AgentIdentity(
            agent_id="test-action-agent",
            runtime_instance_id=uuid.uuid5(
                uuid.NAMESPACE_URL, "rt6-action-agent"
            ),
        ),
        execution=ExecutionIdentity(
            execution_id=uuid.UUID(EXECUTION_ID),
            request_id="req-rt6-action",
        ),
        capabilities=CapabilitySet(
            (
                AgentCapability(
                    name="tool.warranty.claim",
                    scope=CapabilityScope.INVOKE,
                ),
                AgentCapability(
                    name="tool.refund.request",
                    scope=CapabilityScope.INVOKE,
                ),
            )
        ),
        constraints=ExecutionConstraints(),
        causality=CausalityMetadata(),
        tenant_id=TENANT_ID,
        metadata={"session_id": SESSION_ID},
    )


def _warranty_request() -> ToolInvocationRequest:
    return ToolInvocationRequest(
        tool_name="warranty.claim",
        payload={
            "order_id": "order-1",
            "product_sku": "A123",
            "issue_category": "charging_issue",
            "customer_description": "Battery will not charge.",
        },
        metadata={
            "session_id": SESSION_ID,
            "target_resource": TARGET_RESOURCE,
            "tool_name": "warranty.claim",
            "issue_category": "charging_issue",
            "diagnostic_confidence": 0.91,
        },
    )


def _proposal(
    *,
    action: dict[str, Any],
    confidence: float = 0.91,
) -> ResolutionProposalRecord:
    return ResolutionProposalRecord(
        proposal_id=ResolutionProposalId(
            uuid.uuid5(uuid.NAMESPACE_URL, "rt6-proposal")
        ),
        tenant_id=TENANT_ID,
        session_id=SESSION_ID,
        execution_id=EXECUTION_ID,
        dispatch_id=DISPATCH_ID,
        diagnostic_event_id="44444444-4444-4444-8444-444444444444",
        proposed_customer_reply="We can help with the charging issue.",
        resolution_category="charging_issue",
        confidence=confidence,
        supervisor_verdict=ResolutionSupervisorVerdict.PASS,
        governance_verdict=ResolutionGovernanceVerdict.ALLOW,
        autonomy_decision=ResolutionAutonomyDecision.AUTO_APPROVED,
        status=ResolutionProposalStatus.SEND_ELIGIBLE,
        governance_decision_id=uuid.UUID(
            "99999999-9999-4999-8999-999999999999"
        ),
        recommended_actions=(action,),
        evidence=({"rank": 1, "title": "Warranty policy"},),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def _warranty_action() -> dict[str, Any]:
    return {
        "type": "warranty_claim",
        "requires_execution": True,
        "tool_name": "warranty.claim",
        "target_resource_id": TARGET_RESOURCE,
        "payload": dict(_warranty_request().payload),
        "issue_category": "charging_issue",
    }


@pytest.mark.asyncio
async def test_warranty_claim_validates_payload() -> None:
    result = await WarrantyClaimTool().invoke(
        ToolInvocationRequest(
            tool_name="warranty.claim",
            payload={
                "product_sku": "A123",
                "issue_category": "charging_issue",
                "customer_description": "Battery will not charge.",
            },
            metadata={"session_id": SESSION_ID},
        ),
        _context(),
    )

    assert result.status == "error"
    assert result.error_code == "invalid_payload"


@pytest.mark.asyncio
async def test_warranty_claim_derives_deterministic_idempotency_key() -> None:
    tool = WarrantyClaimTool()

    first = await tool.invoke(_warranty_request(), _context())
    second = await tool.invoke(_warranty_request(), _context())
    different_target = await tool.invoke(
        ToolInvocationRequest(
            tool_name="warranty.claim",
            payload=dict(_warranty_request().payload),
            metadata={
                "session_id": SESSION_ID,
                "target_resource": "order:order-2:sku:A123",
            },
        ),
        _context(),
    )

    assert first.status == "success"
    assert first.idempotency_key == second.idempotency_key
    assert first.idempotency_key != different_target.idempotency_key


def test_action_tool_requires_governance() -> None:
    with pytest.raises(ToolConfigurationError):
        ToolInvoker(tool_registry=_registry(WarrantyClaimTool()))


@pytest.mark.asyncio
async def test_action_tool_allow_decision_executes() -> None:
    governance, _ = _governance(Decision.ALLOW)
    invoker = ToolInvoker(
        tool_registry=_registry(WarrantyClaimTool()),
        governance_runtime=governance,
    )

    envelope = await invoker.invoke(
        _warranty_request(),
        _context(),
        invocation_ordinal=1,
    )

    assert envelope.is_ok
    assert envelope.result is not None
    assert envelope.result.status == "success"
    assert envelope.result.idempotency_key is not None


@pytest.mark.asyncio
async def test_action_tool_require_approval_creates_record() -> None:
    calls: list[dict[str, object]] = []
    governance, _ = _governance(Decision.REQUIRE_APPROVAL)
    approvals = InMemoryActionApprovalRepository()
    timeline = _Timeline()
    runtime = ActionOrchestrationRuntime(
        tool_invoker=ToolInvoker(
            tool_registry=_registry(_CountingWarrantyClaimTool(calls)),
            governance_runtime=governance,
        ),
        approval_repository=approvals,
        timeline_runtime=timeline,
    )

    result = await runtime.execute_proposal_actions(
        proposal=_proposal(action=_warranty_action()),
        execution_context=_context(),
        expected_tenant_id=TENANT_ID,
    )

    assert calls == []
    assert result.any_pending_approval is True
    assert result.outcomes[0].status == "pending_approval"
    approval = await approvals.get_by_idempotency_key(
        result.outcomes[0].idempotency_key,
        expected_tenant_id=TENANT_ID,
    )
    assert approval is not None
    assert result.outcomes[0].approval_record_id == approval.approval_id
    assert timeline.events[0]["event_type"] == "action_pending_approval"


@pytest.mark.asyncio
async def test_action_tool_deny_blocks_execution() -> None:
    calls: list[dict[str, object]] = []
    governance, _ = _governance(Decision.DENY)
    timeline = _Timeline()
    runtime = ActionOrchestrationRuntime(
        tool_invoker=ToolInvoker(
            tool_registry=_registry(_CountingWarrantyClaimTool(calls)),
            governance_runtime=governance,
        ),
        approval_repository=InMemoryActionApprovalRepository(),
        timeline_runtime=timeline,
    )

    result = await runtime.execute_proposal_actions(
        proposal=_proposal(action=_warranty_action()),
        execution_context=_context(),
        expected_tenant_id=TENANT_ID,
    )

    assert calls == []
    assert result.any_denied is True
    assert result.outcomes[0].status == "denied"
    assert timeline.events[0]["event_type"] == "action_denied"


@pytest.mark.asyncio
async def test_refund_amount_ceiling() -> None:
    result = await RefundRequestTool().invoke(
        ToolInvocationRequest(
            tool_name="refund.request",
            payload={
                "order_id": "order-1",
                "product_sku": "A123",
                "refund_amount_cents": 100_001,
                "refund_reason": "Customer requested refund.",
            },
            metadata={
                "session_id": SESSION_ID,
                "target_resource": TARGET_RESOURCE,
            },
        ),
        _context(),
    )

    assert result.status == "error"
    assert result.error_code == "invalid_payload"


@requires_postgres
@pytest.mark.asyncio
async def test_approval_record_tenant_isolation(pg_session) -> None:
    repository = PostgresActionApprovalRepository(pg_session)
    idempotency_key = str(
        uuid.uuid5(uuid.NAMESPACE_URL, "tenant-a-action-idempotency")
    )
    record = build_pending_action_approval(
        tenant_id="tenant-a",
        session_id=SESSION_ID,
        execution_id=EXECUTION_ID,
        tool_name="warranty.claim",
        idempotency_key=idempotency_key,
        payload_json={"order_id": "order-1"},
        governance_decision_id=None,
    )
    await repository.create_pending_approval(
        record,
        expected_tenant_id="tenant-a",
    )

    await set_pg_rls_tenant(pg_session, "tenant-a")
    visible = await repository.get_approval(
        record.approval_id,
        expected_tenant_id="tenant-a",
    )
    assert visible is not None

    await set_pg_rls_tenant(pg_session, "tenant-b")
    hidden = await repository.get_approval(
        record.approval_id,
        expected_tenant_id="tenant-b",
    )
    assert hidden is None

"""Phase 2.4 per-tenant action governance break-controls."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.agents.capabilities import (
    AgentCapability,
    CapabilitySet,
    ExecutionConstraints,
)
from app.agents.context import AgentExecutionContext
from app.agents.enums import CapabilityScope
from app.agents.identity import AgentIdentity, ExecutionIdentity
from app.agents.results import ToolInvocationRequest
from app.agents.tools import BaseTool, ToolInvoker, ToolRegistry
from app.agents.tools.action_governance import (
    ACTION_TOOLS_POLICY_TYPE,
    TenantActionPolicy,
    build_action_tool_governance_runtime,
)
from app.agents.tools.actions import (
    RefundRequestTool,
    ReplacementOrderTool,
    WarehouseRepairReportTool,
    WarrantyClaimTool,
)
from app.agents.envelopes import ToolInvocationEnvelope
from app.agents.value_objects import CausalityMetadata
from app.governance.enums import Decision
from app.governance.persistence.memory import InMemoryGovernanceRepository
from app.tenant.chronology import canonical_sha256
from app.tenant.enums import TenantGovernancePolicyStatus
from app.tenant.identity import derive_governance_policy_version_id
from app.tenant.persistence import (
    InMemoryTenantConfigurationRepository,
    TenantGovernancePolicyRecord,
)

pytestmark = pytest.mark.asyncio

_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
_APPROVAL_ID = "approval-2-4-action-policy"
_APPROVED_BY = "policy-admin"


class _DormantRedis:
    async def get(self, _key: str) -> None:
        return None


async def test_2_4_1_refund_thresholds_are_per_tenant() -> None:
    tenant_repository = InMemoryTenantConfigurationRepository()
    await _save_action_policy(
        tenant_repository,
        tenant_id="tenant-a",
        refund_amount_cents_lte=5000,
    )
    await _save_action_policy(
        tenant_repository,
        tenant_id="tenant-b",
        refund_amount_cents_lte=200,
    )

    tenant_a = await _invoke(
        tenant_id="tenant-a",
        tool=RefundRequestTool(),
        request=_refund_request(refund_amount_cents=1000),
        tenant_repository=tenant_repository,
        seed="tenant-a-refund",
    )
    tenant_b = await _invoke(
        tenant_id="tenant-b",
        tool=RefundRequestTool(),
        request=_refund_request(refund_amount_cents=1000),
        tenant_repository=tenant_repository,
        seed="tenant-b-refund",
    )

    assert tenant_a.is_ok
    assert tenant_b.is_denied
    assert tenant_b.trace.metadata["governance_decision"] == (
        Decision.REQUIRE_APPROVAL.value
    )


async def test_2_4_2_missing_policy_denies_with_crisis_policies_present() -> None:
    tenant_repository = InMemoryTenantConfigurationRepository()
    governance_repository = InMemoryGovernanceRepository()

    envelope = await _invoke(
        tenant_id="tenant-without-policy",
        tool=RefundRequestTool(),
        request=_refund_request(refund_amount_cents=1000),
        tenant_repository=tenant_repository,
        governance_repository=governance_repository,
        redis_client=_DormantRedis(),
        seed="missing-policy-crisis-present",
    )

    assert envelope.is_denied
    assert envelope.trace.metadata["governance_decision"] == Decision.DENY.value
    assert envelope.trace.governance_decision_id is not None
    record = await governance_repository.get_decision(
        str(envelope.trace.governance_decision_id),
        expected_tenant_id="tenant-without-policy",
    )
    assert record is not None
    assert any(
        rule.policy_name.startswith("crisis.")
        and rule.decision == Decision.ALLOW.value
        for rule in record.evaluated_rules
    )
    assert any(
        rule.policy_name == TenantActionPolicy.name
        and rule.decision == Decision.DENY.value
        and "no active" in rule.reason
        for rule in record.evaluated_rules
    )


async def test_2_4_3_anker_seeded_policy_preserves_prior_decisions() -> None:
    tenant_repository = InMemoryTenantConfigurationRepository()
    await _save_action_policy(
        tenant_repository,
        tenant_id="anker-pilot",
        refund_amount_cents_lte=5000,
    )

    cases = (
        (
            RefundRequestTool(),
            _refund_request(refund_amount_cents=5000),
            Decision.ALLOW,
            "anker-refund-allow",
        ),
        (
            RefundRequestTool(),
            _refund_request(refund_amount_cents=5001),
            Decision.REQUIRE_APPROVAL,
            "anker-refund-approval",
        ),
        (
            ReplacementOrderTool(),
            _replacement_request(),
            Decision.REQUIRE_APPROVAL,
            "anker-replacement-approval",
        ),
        (
            WarrantyClaimTool(),
            _warranty_request(
                issue_category="charging_issue",
                diagnostic_confidence=0.85,
            ),
            Decision.ALLOW,
            "anker-warranty-charging-allow",
        ),
        (
            WarrantyClaimTool(),
            _warranty_request(
                issue_category="product_defect",
                diagnostic_confidence=0.85,
            ),
            Decision.ALLOW,
            "anker-warranty-defect-allow",
        ),
        (
            WarrantyClaimTool(),
            _warranty_request(
                issue_category="charging_issue",
                diagnostic_confidence=0.84,
            ),
            Decision.REQUIRE_APPROVAL,
            "anker-warranty-confidence-approval",
        ),
        (
            WarehouseRepairReportTool(),
            _warehouse_request(severity="medium"),
            Decision.ALLOW,
            "anker-warehouse-medium-allow",
        ),
        (
            WarehouseRepairReportTool(),
            _warehouse_request(severity="high"),
            Decision.REQUIRE_APPROVAL,
            "anker-warehouse-high-approval",
        ),
    )

    for tool, request, expected, seed in cases:
        envelope = await _invoke(
            tenant_id="anker-pilot",
            tool=tool,
            request=request,
            tenant_repository=tenant_repository,
            seed=seed,
        )
        if expected is Decision.ALLOW:
            assert envelope.is_ok, seed
        else:
            assert envelope.is_denied, seed
            assert envelope.trace.metadata["governance_decision"] == expected.value


async def test_2_4_4_decision_binds_reconstructible_policy_version() -> None:
    tenant_repository = InMemoryTenantConfigurationRepository()
    await _save_action_policy(
        tenant_repository,
        tenant_id="tenant-binding",
        refund_amount_cents_lte=200,
        version=1,
    )
    active = await _save_action_policy(
        tenant_repository,
        tenant_id="tenant-binding",
        refund_amount_cents_lte=5000,
        version=2,
    )
    governance_repository = InMemoryGovernanceRepository()

    envelope = await _invoke(
        tenant_id="tenant-binding",
        tool=RefundRequestTool(),
        request=_refund_request(refund_amount_cents=1000),
        tenant_repository=tenant_repository,
        governance_repository=governance_repository,
        seed="tenant-binding-refund",
    )

    assert envelope.is_ok
    assert envelope.trace.governance_decision_id is not None
    decision = await governance_repository.get_decision(
        str(envelope.trace.governance_decision_id),
        expected_tenant_id="tenant-binding",
    )
    assert decision is not None
    rule = next(
        rule
        for rule in decision.evaluated_rules
        if rule.policy_name == TenantActionPolicy.name
    )
    assert rule.metadata["action_policy.policy_id"] == str(active.policy_id)
    assert rule.metadata["action_policy.version"] == active.version
    assert (
        rule.metadata["action_policy.content_sha256"] == active.content_sha256
    )
    assert rule.policy_version != "unversioned"

    reconstructed = await tenant_repository.get_governance_policy(
        active.policy_id,
        expected_tenant_id="tenant-binding",
    )
    assert reconstructed is not None
    assert reconstructed.version == active.version
    assert reconstructed.content_sha256 == active.content_sha256


async def _invoke(
    *,
    tenant_id: str,
    tool: BaseTool,
    request: ToolInvocationRequest,
    tenant_repository: InMemoryTenantConfigurationRepository,
    seed: str,
    governance_repository: InMemoryGovernanceRepository | None = None,
    redis_client: object | None = None,
) -> ToolInvocationEnvelope:
    registry = ToolRegistry()
    registry.register(tool)
    persistence = governance_repository or InMemoryGovernanceRepository()
    invoker = ToolInvoker(
        tool_registry=registry,
        governance_runtime=build_action_tool_governance_runtime(
            persistence=persistence,
            redis_client=redis_client,
            tenant_configuration_repository=tenant_repository,
        ),
    )
    return await invoker.invoke(
        request,
        _context(tenant_id=tenant_id, seed=seed),
        invocation_ordinal=1,
    )


def _context(*, tenant_id: str, seed: str) -> AgentExecutionContext:
    return AgentExecutionContext(
        identity=AgentIdentity(
            agent_id="test-action-agent",
            runtime_instance_id=uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"2.4-action-runtime:{seed}",
            ),
        ),
        execution=ExecutionIdentity(
            execution_id=uuid.uuid5(uuid.NAMESPACE_URL, f"2.4-exec:{seed}"),
            request_id=f"req-2-4-{seed}",
        ),
        capabilities=CapabilitySet(
            (
                AgentCapability(
                    name="tool.refund.request",
                    scope=CapabilityScope.INVOKE,
                ),
                AgentCapability(
                    name="tool.replacement.order",
                    scope=CapabilityScope.INVOKE,
                ),
                AgentCapability(
                    name="tool.warranty.claim",
                    scope=CapabilityScope.INVOKE,
                ),
                AgentCapability(
                    name="tool.warehouse.repair",
                    scope=CapabilityScope.INVOKE,
                ),
                AgentCapability(
                    name="tool.unknown.action",
                    scope=CapabilityScope.INVOKE,
                ),
            )
        ),
        constraints=ExecutionConstraints(),
        causality=CausalityMetadata(),
        tenant_id=tenant_id,
        metadata={"session_id": f"session-{seed}"},
    )


def _refund_request(*, refund_amount_cents: int) -> ToolInvocationRequest:
    return ToolInvocationRequest(
        tool_name="refund.request",
        payload={
            "order_id": "order-1",
            "product_sku": "A123",
            "refund_amount_cents": refund_amount_cents,
            "refund_reason": "Customer requested refund.",
        },
        metadata={
            "session_id": "session-refund",
            "tool_name": "refund.request",
            "action_type": "refund_request",
            "target_resource": "refund:order-1",
            "refund_amount_cents": refund_amount_cents,
            "diagnostic_confidence": 0.92,
        },
    )


def _replacement_request() -> ToolInvocationRequest:
    return ToolInvocationRequest(
        tool_name="replacement.order",
        payload={
            "order_id": "order-1",
            "product_sku": "A123",
            "replacement_reason": "Customer requested replacement.",
            "shipping_address_hash": "address-hash",
        },
        metadata={
            "session_id": "session-replacement",
            "tool_name": "replacement.order",
            "action_type": "replacement_order",
            "target_resource": "replacement:order-1",
        },
    )


def _warranty_request(
    *,
    issue_category: str,
    diagnostic_confidence: float,
) -> ToolInvocationRequest:
    return ToolInvocationRequest(
        tool_name="warranty.claim",
        payload={
            "order_id": "order-1",
            "product_sku": "A123",
            "issue_category": issue_category,
            "customer_description": "Customer reported a product issue.",
        },
        metadata={
            "session_id": "session-warranty",
            "tool_name": "warranty.claim",
            "action_type": "warranty_claim",
            "target_resource": f"warranty:{issue_category}",
            "issue_category": issue_category,
            "diagnostic_confidence": diagnostic_confidence,
        },
    )


def _warehouse_request(*, severity: str) -> ToolInvocationRequest:
    return ToolInvocationRequest(
        tool_name="warehouse.repair.report",
        payload={
            "product_sku": "A123",
            "batch_id": None,
            "defect_description": "Customer reported a product issue.",
            "severity": severity,
            "session_id": "session-warehouse",
        },
        metadata={
            "session_id": "session-warehouse",
            "tool_name": "warehouse.repair.report",
            "action_type": "warehouse_repair",
            "target_resource": f"warehouse:{severity}",
            "severity": severity,
        },
    )


async def _save_action_policy(
    repository: InMemoryTenantConfigurationRepository,
    *,
    tenant_id: str,
    refund_amount_cents_lte: int,
    version: int = 1,
) -> TenantGovernancePolicyRecord:
    parameters = _action_policy_parameters(
        refund_amount_cents_lte=refund_amount_cents_lte
    )
    record = _policy_record(
        tenant_id=tenant_id,
        parameters=parameters,
        version=version,
    )
    await repository.save_governance_policy(
        record,
        expected_tenant_id=tenant_id,
    )
    return record


def _policy_record(
    *,
    tenant_id: str,
    parameters: dict[str, object],
    version: int,
) -> TenantGovernancePolicyRecord:
    content_sha256 = canonical_sha256(
        {
            "tenant_id": tenant_id,
            "policy_type": ACTION_TOOLS_POLICY_TYPE,
            "parameters": parameters,
            "status": TenantGovernancePolicyStatus.ACTIVE.value,
            "version": version,
            "approved_by": _APPROVED_BY,
            "effective_from": _NOW.isoformat(),
            "source_approval_id": _APPROVAL_ID,
        }
    )
    return TenantGovernancePolicyRecord(
        policy_id=derive_governance_policy_version_id(
            tenant_id=tenant_id,
            policy_type=ACTION_TOOLS_POLICY_TYPE,
            version=version,
        ),
        tenant_id=tenant_id,
        policy_type=ACTION_TOOLS_POLICY_TYPE,
        parameters=parameters,
        status=TenantGovernancePolicyStatus.ACTIVE,
        version=version,
        approved_by=_APPROVED_BY,
        effective_from=_NOW,
        created_at=_NOW,
        source_approval_id=_APPROVAL_ID,
        content_sha256=content_sha256,
        previous_version_sha256=None,
    )


def _action_policy_parameters(
    *,
    refund_amount_cents_lte: int,
) -> dict[str, object]:
    return {
        "phase": "2.4",
        "tools": {
            "warranty.claim": {
                "allow": {
                    "confidence_gte": 0.85,
                    "issue_category_in": [
                        "charging_issue",
                        "product_defect",
                    ],
                },
                "else": "require_approval",
            },
            "replacement.order": {"always": "require_approval"},
            "refund.request": {
                "allow": {
                    "refund_amount_cents_lte": refund_amount_cents_lte
                },
                "else": "require_approval",
            },
            "warehouse.repair.report": {
                "allow": {"severity_in": ["low", "medium"]},
                "require_approval": {"severity_in": ["high", "critical"]},
            },
        },
    }

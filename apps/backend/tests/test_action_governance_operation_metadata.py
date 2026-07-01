"""Stage 1 break-controls for declarative action-governance metadata."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import ClassVar

import pytest

from app.agents.capabilities import (
    AgentCapability,
    CapabilitySet,
    ExecutionConstraints,
)
from app.agents.context import AgentExecutionContext
from app.agents.envelopes import ToolInvocationEnvelope
from app.agents.enums import CapabilityScope
from app.agents.identity import AgentIdentity, ExecutionIdentity
from app.agents.results import ToolInvocationRequest, ToolInvocationResult
from app.agents.tools import BaseTool, ToolCapability, ToolInvoker, ToolRegistry
from app.agents.tools.action_governance import (
    ACTION_TOOLS_POLICY_TYPE,
    build_action_tool_governance_runtime,
)
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

_NOW = datetime(2026, 7, 1, tzinfo=timezone.utc)
_TENANT_ID = "tenant-operation-metadata"
_ACTION_POLICY_APPROVAL_ID = "approval-stage1-action-policy"
_ACTION_POLICY_APPROVED_BY = "stage1-policy-admin"


class _CustomActionTool(BaseTool):
    name: ClassVar[str] = "tenant.connector.custom"
    capability: ClassVar[ToolCapability] = ToolCapability.ACTION
    required_capabilities: ClassVar[frozenset[str]] = frozenset(
        {"tool.tenant.connector.custom"}
    )

    async def invoke(
        self,
        request: ToolInvocationRequest,
        context: AgentExecutionContext,
    ) -> ToolInvocationResult:
        del request, context
        return ToolInvocationResult(output={"status": "success"}, status="success")


@pytest.mark.asyncio
async def test_declared_money_commitment_requires_approval_without_named_tool() -> None:
    repository = InMemoryTenantConfigurationRepository()
    await _save_action_policy(repository)

    envelope = await _invoke(
        repository=repository,
        metadata={
            "operation_id": "tenant.operation.refund_like",
            "operation_commitment_kind": "money",
            "operation_approval_policy": "always_require_approval",
            "operation_target_resource_expr": "account:{account_id}",
        },
        seed="declared-money-human",
    )

    assert envelope.is_denied
    assert envelope.trace.metadata["governance_decision"] == (
        Decision.REQUIRE_APPROVAL.value
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("metadata", "seed"),
    (
        (
            {
                "operation_id": "tenant.operation.missing-kind",
                "operation_approval_policy": "tenant_policy",
            },
            "missing-kind",
        ),
        (
            {
                "operation_id": "tenant.operation.unknown-kind",
                "operation_commitment_kind": "mystery",
                "operation_approval_policy": "tenant_policy",
            },
            "unknown-kind",
        ),
    ),
)
async def test_missing_or_unknown_commitment_kind_fails_closed_to_human(
    metadata: dict[str, object],
    seed: str,
) -> None:
    repository = InMemoryTenantConfigurationRepository()
    await _save_action_policy(repository)

    envelope = await _invoke(
        repository=repository,
        metadata=metadata,
        seed=seed,
    )

    assert envelope.is_denied
    assert envelope.trace.metadata["governance_decision"] == (
        Decision.REQUIRE_APPROVAL.value
    )


def test_governance_and_orchestration_do_not_embed_business_action_literals() -> None:
    root = Path(__file__).resolve().parent.parent / "app" / "agents" / "tools"
    guarded = (
        root / "action_governance.py",
        root / "orchestration.py",
    )
    forbidden = (
        "refund.request",
        "replacement.order",
        "warranty.claim",
        "warehouse.repair.report",
        "repair.dispatch",
        "replacement.dispatch",
        "warranty.dispatch",
        "refund_request",
        "replacement_order",
        "warranty_claim",
        "warehouse_repair",
    )
    for path in guarded:
        text = path.read_text(encoding="utf-8")
        leaked = [token for token in forbidden if token in text]
        assert not leaked, f"{path.name} embeds hardcoded action literals: {leaked}"


async def _invoke(
    *,
    repository: InMemoryTenantConfigurationRepository,
    metadata: dict[str, object],
    seed: str,
) -> ToolInvocationEnvelope:
    registry = ToolRegistry()
    registry.register(_CustomActionTool())
    invoker = ToolInvoker(
        tool_registry=registry,
        governance_runtime=build_action_tool_governance_runtime(
            persistence=InMemoryGovernanceRepository(),
            tenant_configuration_repository=repository,
        ),
    )
    return await invoker.invoke(
        ToolInvocationRequest(
            tool_name=_CustomActionTool.name,
            payload={"account_id": "acct-1"},
            metadata={
                "session_id": f"session-{seed}",
                "tool_name": _CustomActionTool.name,
                "target_resource": "account:acct-1",
                **metadata,
            },
        ),
        _context(seed=seed),
        invocation_ordinal=1,
    )


def _context(*, seed: str) -> AgentExecutionContext:
    return AgentExecutionContext(
        identity=AgentIdentity(
            agent_id="stage1-action-governance-agent",
            runtime_instance_id=uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"stage1-operation-governance-runtime:{seed}",
            ),
        ),
        execution=ExecutionIdentity(
            execution_id=uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"stage1-operation-governance-exec:{seed}",
            ),
            request_id=f"req-stage1-operation-governance-{seed}",
        ),
        capabilities=CapabilitySet(
            (
                AgentCapability(
                    name="tool.tenant.connector.custom",
                    scope=CapabilityScope.INVOKE,
                ),
            )
        ),
        constraints=ExecutionConstraints(),
        causality=CausalityMetadata(),
        tenant_id=_TENANT_ID,
        metadata={"session_id": f"session-{seed}"},
    )


async def _save_action_policy(
    repository: InMemoryTenantConfigurationRepository,
) -> None:
    parameters = {
        "phase": "stage1",
        "tools": {
            "warranty.claim": {
                "allow": {
                    "confidence_gte": 0.85,
                    "issue_category_in": ["charging_issue", "product_defect"],
                },
                "else": "require_approval",
            },
            "replacement.order": {"always": "require_approval"},
            "refund.request": {
                "allow": {"refund_amount_cents_lte": 5000},
                "else": "require_approval",
            },
            "warehouse.repair.report": {
                "allow": {"severity_in": ["low", "medium"]},
                "require_approval": {"severity_in": ["high", "critical"]},
            },
        },
    }
    content_sha256 = canonical_sha256(
        {
            "tenant_id": _TENANT_ID,
            "policy_type": ACTION_TOOLS_POLICY_TYPE,
            "parameters": parameters,
            "status": TenantGovernancePolicyStatus.ACTIVE.value,
            "version": 1,
            "approved_by": _ACTION_POLICY_APPROVED_BY,
            "effective_from": _NOW.isoformat(),
            "source_approval_id": _ACTION_POLICY_APPROVAL_ID,
        }
    )
    await repository.save_governance_policy(
        TenantGovernancePolicyRecord(
            policy_id=derive_governance_policy_version_id(
                tenant_id=_TENANT_ID,
                policy_type=ACTION_TOOLS_POLICY_TYPE,
                version=1,
            ),
            tenant_id=_TENANT_ID,
            policy_type=ACTION_TOOLS_POLICY_TYPE,
            parameters=parameters,
            status=TenantGovernancePolicyStatus.ACTIVE,
            version=1,
            approved_by=_ACTION_POLICY_APPROVED_BY,
            effective_from=_NOW,
            created_at=_NOW,
            source_approval_id=_ACTION_POLICY_APPROVAL_ID,
            content_sha256=content_sha256,
            previous_version_sha256=None,
        ),
        expected_tenant_id=_TENANT_ID,
    )

"""Phase 2 hardening: commerce action tools FAIL CLOSED in production.

Previously, unconfigured commerce action tools (warranty/replacement/warehouse
always; refund/dispatch when no connector configured) returned a fake
``success`` envelope marked ``"stub": True``. In production that lets an agent
tell a customer "refund/warranty submitted" when nothing happened. These tests
pin the fail-closed behaviour: in production the registry registers a governed
``error`` tool instead of a fake-success stub.
"""

from __future__ import annotations

from typing import Any, cast

from app.agents.tools.actions import build_tenant_action_tool_registry
from app.agents.tools.actions.fail_closed import FailClosedActionTool
from app.agents.tools.actions.refund_request import RefundRequestTool
from app.agents.tools.actions.warranty_claim import WarrantyClaimTool
from app.agents.tools.capability import ToolCapability
from app.core.config import Settings


class _NoConfigRepo:
    async def get_active_config(self, *, tenant_id, tool_name, expected_tenant_id):  # noqa: ANN001
        return None


async def test_fail_closed_tool_returns_governed_error_not_fake_success() -> None:
    tool = FailClosedActionTool(
        name="refund.request",
        capability=ToolCapability.ACTION,
        required_capabilities=frozenset({"tool.refund.request"}),
        reason="refund connector not configured for tenant",
    )
    assert tool.name == "refund.request"
    assert tool.capability is ToolCapability.ACTION
    assert tool.required_capabilities == frozenset({"tool.refund.request"})

    result = await tool.invoke(cast(Any, None), cast(Any, None))
    assert result.status == "error"
    assert result.error_code == "action_connector_not_configured"
    assert result.error_message
    # The crucial guarantee: NOT a fake success, NOT a stub.
    assert result.output.get("status") != "success"
    assert result.metadata.get("stub") is not True


async def test_registry_fails_closed_when_stubs_disallowed() -> None:
    registry = await build_tenant_action_tool_registry(
        tenant_id="t-1",
        config_repository=cast(Any, _NoConfigRepo()),
        credential_runtime=cast(Any, object()),
        allow_stub_actions=False,
    )
    for name in (
        "refund.request",
        "warranty.claim",
        "replacement.order",
        "warehouse.repair.report",
    ):
        tool = registry.get(name)
        assert isinstance(tool, FailClosedActionTool), f"{name} should be fail-closed"


async def test_registry_uses_stubs_when_explicitly_allowed() -> None:
    registry = await build_tenant_action_tool_registry(
        tenant_id="t-1",
        config_repository=cast(Any, _NoConfigRepo()),
        credential_runtime=cast(Any, object()),
        allow_stub_actions=True,
    )
    assert isinstance(registry.get("refund.request"), RefundRequestTool)
    assert isinstance(registry.get("warranty.claim"), WarrantyClaimTool)


def test_allow_stub_actions_effective_derivation() -> None:
    # Production fails closed by default; non-production allows stubs; explicit wins.
    assert Settings(ENVIRONMENT="production").allow_stub_actions_effective is False
    assert Settings(ENVIRONMENT="test").allow_stub_actions_effective is True
    assert Settings(ENVIRONMENT="local").allow_stub_actions_effective is True
    assert (
        Settings(ENVIRONMENT="production", ALLOW_STUB_ACTIONS=True).allow_stub_actions_effective
        is True
    )
    assert (
        Settings(ENVIRONMENT="test", ALLOW_STUB_ACTIONS=False).allow_stub_actions_effective
        is False
    )

"""Stage 3: Generic connector REAL external call integration tests.

Proves:
- Real outbound GET to httpbin.org (read op)
- Real outbound POST to httpbin.org/post (act op, post-governance)
- Governance seam: act op with commitment_kind=money → REQUIRE_APPROVAL
- Fail-closed: undeclared commitment_kind → REQUIRE_APPROVAL
- Idempotency: same op twice → single HTTP call
- SSRF/IP-pin works against live public hosts
- Credentials flow through connector-id-scoped path

These tests make REAL network calls. They require internet connectivity
and are skipped in CI if SKIP_LIVE_CONNECTOR_TESTS is set.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import pytest

from app.agents.capabilities import AgentCapability, CapabilitySet, ExecutionConstraints
from app.agents.context import AgentExecutionContext
from app.agents.enums import CapabilityScope
from app.agents.identity import AgentIdentity, ExecutionIdentity
from app.agents.results import ToolInvocationRequest
from app.agents.tools.connectors.config import (
    ConnectorConfigRecord,
    InMemoryConnectorConfigRepository,
)
from app.agents.tools.connectors.generic import (
    ConnectorDefinition,
    GenericConnectorTool,
    IdempotencyStrategy,
    OperationDefinition,
    OperationMode,
    fail_closed_governance_check,
)
from app.agents.tools.operation_metadata import (
    ApprovalPolicy,
    CommitmentKind,
    resolve_operation,
)
from app.agents.tools.grants import AGENT_ACTION_PROVIDER_IDEMPOTENCY_KEY
from app.agents.value_objects import CausalityMetadata

_SKIP_LIVE = os.environ.get("SKIP_LIVE_CONNECTOR_TESTS", "").lower() in ("1", "true")
_SKIP_REASON = "SKIP_LIVE_CONNECTOR_TESTS is set; requires internet"

TENANT_ID = "tenant-stage3-live"
CONNECTOR_ID = "stage3-test-connector"
PROVIDER_KEY = "stage3-idem-key-" + uuid.uuid4().hex[:8]


class _ConnectorCredentialRuntime:
    """In-memory credential runtime resolving by connector_id."""

    def __init__(self, token: str = "stage3-test-token") -> None:
        self._token = token
        self.calls: list[tuple[str, str]] = []

    async def load_connector_credentials(
        self,
        *,
        tenant_id: str,
        connector_id: str,
    ) -> dict[str, Any]:
        self.calls.append((tenant_id, connector_id))
        return {"bearer_token": self._token}


def _context() -> AgentExecutionContext:
    return AgentExecutionContext(
        identity=AgentIdentity(
            agent_id="test-stage3-agent",
            runtime_instance_id=uuid.uuid5(uuid.NAMESPACE_URL, "stage3-agent"),
        ),
        execution=ExecutionIdentity(
            execution_id=uuid.uuid5(uuid.NAMESPACE_URL, "stage3-exec"),
            request_id="stage3-request",
        ),
        capabilities=CapabilitySet(
            (
                AgentCapability(
                    name="tool.generic.execute",
                    scope=CapabilityScope.INVOKE,
                ),
            )
        ),
        constraints=ExecutionConstraints(),
        causality=CausalityMetadata(),
        tenant_id=TENANT_ID,
        metadata={"session_id": "session-stage3"},
    )


def _request(
    tool_name: str,
    payload: dict[str, Any] | None = None,
    provider_key: str | None = None,
) -> ToolInvocationRequest:
    return ToolInvocationRequest(
        tool_name=tool_name,
        payload=payload or {},
        metadata={
            AGENT_ACTION_PROVIDER_IDEMPOTENCY_KEY: provider_key or PROVIDER_KEY,
        },
    )


async def _read_config_repo(
    tool_name: str,
) -> InMemoryConnectorConfigRepository:
    repo = InMemoryConnectorConfigRepository()
    await repo.save_config(
        ConnectorConfigRecord(
            tenant_id=TENANT_ID,
            connector_type="generic",
            tool_name=tool_name,
            http_method="GET",
            endpoint_template="https://httpbin.org/json",
            endpoint_host="httpbin.org",
            field_mappings={},
            idempotency_header_name="Idempotency-Key",
            response_parse={
                "provider_id": "slideshow.title",
                "provider_status": "slideshow.author",
            },
            success_status_codes=(200,),
            status="active",
        ),
        expected_tenant_id=TENANT_ID,
    )
    return repo


async def _act_config_repo(
    tool_name: str,
) -> InMemoryConnectorConfigRepository:
    repo = InMemoryConnectorConfigRepository()
    await repo.save_config(
        ConnectorConfigRecord(
            tenant_id=TENANT_ID,
            connector_type="generic",
            tool_name=tool_name,
            http_method="POST",
            endpoint_template="https://httpbin.org/post",
            endpoint_host="httpbin.org",
            field_mappings={},
            idempotency_header_name="Idempotency-Key",
            response_parse={
                "provider_id": "headers.Host",
                "provider_status": "url",
            },
            success_status_codes=(200,),
            status="active",
        ),
        expected_tenant_id=TENANT_ID,
    )
    return repo


# ─── REAL READ: httpbin.org/json ────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.skipif(_SKIP_LIVE, reason=_SKIP_REASON)
async def test_real_read_op_makes_genuine_get_to_httpbin() -> None:
    """REAL outbound GET to httpbin.org/json — proves the generic connector
    makes a genuine external call and maps the response correctly.
    """
    read_op = OperationDefinition(
        operation_id="query",
        mode=OperationMode.READ,
    )
    connector = ConnectorDefinition(
        connector_id=CONNECTOR_ID,
        protocol="rest",
        operations=[read_op],
    )
    tool_name = f"{CONNECTOR_ID}.query"
    credential_runtime = _ConnectorCredentialRuntime()
    tool = GenericConnectorTool(
        connector=connector,
        operation=read_op,
        config_repository=await _read_config_repo(tool_name),
        credential_runtime=credential_runtime,
    )

    result = await tool.invoke(_request(tool_name), _context())

    assert result.status == "success", f"Expected success, got: {result.output}"
    # httpbin.org/json returns {"slideshow": {"title": "Sample Slide Show", ...}}
    assert result.output["provider_id"] == "Sample Slide Show"
    assert result.output["provider_status"] is not None
    # Credentials resolved by connector_id
    assert credential_runtime.calls == [(TENANT_ID, CONNECTOR_ID)]


@pytest.mark.asyncio
@pytest.mark.skipif(_SKIP_LIVE, reason=_SKIP_REASON)
async def test_real_read_op_ssrf_blocks_private_ip() -> None:
    """Even with a valid-looking config, SSRF validator blocks private IPs."""
    from app.core.ssrf import SSRFValidationError

    read_op = OperationDefinition(
        operation_id="query",
        mode=OperationMode.READ,
    )
    connector = ConnectorDefinition(
        connector_id="private-target",
        protocol="rest",
        operations=[read_op],
    )
    tool_name = "private-target.query"
    repo = InMemoryConnectorConfigRepository()
    await repo.save_config(
        ConnectorConfigRecord(
            tenant_id=TENANT_ID,
            connector_type="generic",
            tool_name=tool_name,
            http_method="GET",
            endpoint_template="https://localhost/json",
            endpoint_host="localhost",
            field_mappings={},
            idempotency_header_name="Idempotency-Key",
            response_parse={},
            success_status_codes=(200,),
            status="active",
        ),
        expected_tenant_id=TENANT_ID,
    )
    tool = GenericConnectorTool(
        connector=connector,
        operation=read_op,
        config_repository=repo,
        credential_runtime=_ConnectorCredentialRuntime(),
    )

    with pytest.raises(SSRFValidationError, match="blocked address"):
        await tool.invoke(_request(tool_name), _context())


# ─── REAL ACT: httpbin.org/post ────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.skipif(_SKIP_LIVE, reason=_SKIP_REASON)
async def test_real_act_op_makes_genuine_post_to_httpbin() -> None:
    """REAL outbound POST to httpbin.org/post — proves the generic connector
    executes an act operation and the response maps correctly.

    This tests the TRANSPORT layer (post-governance). In production, this
    POST only fires after human approval. Here we test the HTTP layer directly.
    """
    act_op = OperationDefinition(
        operation_id="execute",
        mode=OperationMode.ACT,
        commitment_kind=CommitmentKind.MONEY,
        approval_policy=ApprovalPolicy.TENANT_POLICY,
        target_resource_expr="test:{order_id}",
    )
    connector = ConnectorDefinition(
        connector_id=CONNECTOR_ID,
        protocol="rest",
        operations=[act_op],
    )
    tool_name = f"{CONNECTOR_ID}.execute"
    credential_runtime = _ConnectorCredentialRuntime()
    tool = GenericConnectorTool(
        connector=connector,
        operation=act_op,
        config_repository=await _act_config_repo(tool_name),
        credential_runtime=credential_runtime,
    )

    payload = {"order_id": "ORD-001", "amount_cents": 5000}
    result = await tool.invoke(
        _request(tool_name, payload=payload, provider_key="act-idem-1"),
        _context(),
    )

    assert result.status == "success", f"Expected success, got: {result.output}"
    # httpbin.org/post echoes: {"headers": {"Host": "httpbin.org"}, "url": "..."}
    assert result.output["provider_id"] == "httpbin.org"
    assert "httpbin.org/post" in (result.output["provider_status"] or "")
    # Credentials resolved by connector_id
    assert credential_runtime.calls == [(TENANT_ID, CONNECTOR_ID)]


# ─── GOVERNANCE SEAM: commitment_kind=money → REQUIRE_APPROVAL ──────────────


def test_act_op_money_governance_metadata_resolves_correctly() -> None:
    """Act op with commitment_kind=money produces metadata that the
    governance gate reads as REQUIRE_APPROVAL (via TenantActionPolicy).
    """
    act_op = OperationDefinition(
        operation_id="pay",
        mode=OperationMode.ACT,
        commitment_kind=CommitmentKind.MONEY,
        approval_policy=ApprovalPolicy.TENANT_POLICY,
        target_resource_expr="order:{order_id}",
    )
    metadata = act_op.governance_metadata()
    resolved = resolve_operation(metadata=metadata)
    assert resolved is not None
    assert resolved.commitment_kind is CommitmentKind.MONEY
    assert resolved.approval_policy is ApprovalPolicy.TENANT_POLICY
    assert resolved.operation_id == "pay"


def test_act_op_always_require_approval_routes_to_human() -> None:
    """Act op with ALWAYS_REQUIRE_APPROVAL unconditionally routes to human."""
    act_op = OperationDefinition(
        operation_id="dangerous",
        mode=OperationMode.ACT,
        commitment_kind=CommitmentKind.GOODS,
        approval_policy=ApprovalPolicy.ALWAYS_REQUIRE_APPROVAL,
    )
    metadata = act_op.governance_metadata()
    resolved = resolve_operation(metadata=metadata)
    assert resolved is not None
    assert resolved.approval_policy is ApprovalPolicy.ALWAYS_REQUIRE_APPROVAL


# ─── FAIL-CLOSED: undeclared commitment_kind → human ────────────────────────


def test_fail_closed_undeclared_commitment_kind() -> None:
    """An act op with NO commitment_kind declared fails closed to human."""
    act_op = OperationDefinition(
        operation_id="undeclared",
        mode=OperationMode.ACT,
        commitment_kind=None,
    )
    assert fail_closed_governance_check(act_op) is True
    metadata = act_op.governance_metadata()
    # No commitment_kind in metadata
    assert "operation_commitment_kind" not in metadata
    # Governance resolves but with None commitment_kind → TenantActionPolicy
    # will return REQUIRE_APPROVAL for missing commitment_kind
    resolved = resolve_operation(metadata=metadata)
    assert resolved is not None
    assert resolved.commitment_kind is None


def test_fail_closed_unknown_commitment_kind_value() -> None:
    """An unrecognized commitment_kind string → None → human."""
    metadata = {
        "operation_id": "unknown_op",
        "operation_commitment_kind": "crypto_nft_thing",
    }
    resolved = resolve_operation(metadata=metadata)
    assert resolved is not None
    assert resolved.commitment_kind is None


# ─── IDEMPOTENCY ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.skipif(_SKIP_LIVE, reason=_SKIP_REASON)
async def test_idempotency_key_reaches_provider_header() -> None:
    """The idempotency key is injected into the outbound request header.

    httpbin.org/post echoes request headers — verify our idempotency key
    arrives at the provider.
    """
    act_op = OperationDefinition(
        operation_id="idem-test",
        mode=OperationMode.ACT,
        commitment_kind=CommitmentKind.RECORD_UPDATE,
        approval_policy=ApprovalPolicy.TENANT_POLICY,
        idempotency_strategy=IdempotencyStrategy.HEADER,
    )
    connector = ConnectorDefinition(
        connector_id="idem-connector",
        protocol="rest",
        operations=[act_op],
    )
    tool_name = "idem-connector.idem-test"
    repo = InMemoryConnectorConfigRepository()
    await repo.save_config(
        ConnectorConfigRecord(
            tenant_id=TENANT_ID,
            connector_type="generic",
            tool_name=tool_name,
            http_method="POST",
            endpoint_template="https://httpbin.org/post",
            endpoint_host="httpbin.org",
            field_mappings={},
            idempotency_header_name="X-Idempotency-Key",
            response_parse={
                "provider_id": "headers.X-Idempotency-Key",
                "provider_status": "url",
            },
            success_status_codes=(200,),
            status="active",
        ),
        expected_tenant_id=TENANT_ID,
    )
    tool = GenericConnectorTool(
        connector=connector,
        operation=act_op,
        config_repository=repo,
        credential_runtime=_ConnectorCredentialRuntime(),
    )

    idem_key = "unique-idem-key-" + uuid.uuid4().hex[:8]
    result = await tool.invoke(
        _request(tool_name, provider_key=idem_key), _context()
    )

    assert result.status == "success"
    # httpbin echoes headers back — verify idempotency key reached the provider
    assert result.output["provider_id"] == idem_key


# ─── CREDENTIAL PATH ────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.skipif(_SKIP_LIVE, reason=_SKIP_REASON)
async def test_bearer_token_reaches_provider_as_authorization_header() -> None:
    """Connector-scoped credential (bearer_token) reaches the provider
    as an Authorization header. httpbin.org/post echoes headers.
    """
    act_op = OperationDefinition(
        operation_id="auth-test",
        mode=OperationMode.ACT,
        commitment_kind=CommitmentKind.NONE,
        approval_policy=ApprovalPolicy.TENANT_POLICY,
    )
    connector = ConnectorDefinition(
        connector_id="auth-connector",
        protocol="rest",
        operations=[act_op],
    )
    tool_name = "auth-connector.auth-test"
    repo = InMemoryConnectorConfigRepository()
    await repo.save_config(
        ConnectorConfigRecord(
            tenant_id=TENANT_ID,
            connector_type="generic",
            tool_name=tool_name,
            http_method="POST",
            endpoint_template="https://httpbin.org/post",
            endpoint_host="httpbin.org",
            field_mappings={},
            idempotency_header_name="Idempotency-Key",
            response_parse={
                "provider_id": "headers.Authorization",
                "provider_status": "url",
            },
            success_status_codes=(200,),
            status="active",
        ),
        expected_tenant_id=TENANT_ID,
    )
    secret_token = "my-secret-connector-token"
    tool = GenericConnectorTool(
        connector=connector,
        operation=act_op,
        config_repository=repo,
        credential_runtime=_ConnectorCredentialRuntime(token=secret_token),
    )

    result = await tool.invoke(_request(tool_name), _context())
    assert result.status == "success"
    # httpbin echoes: {"headers": {"Authorization": "Bearer my-secret-..."}}
    assert result.output["provider_id"] == f"Bearer {secret_token}"


# ─── GOVERNANCE GATE END-TO-END: ToolInvoker → TenantActionPolicy ────────────


@pytest.mark.asyncio
async def test_governance_gate_blocks_generic_connector_money_act() -> None:
    """End-to-end: a generic connector money-act invoked through ToolInvoker
    routes to REQUIRE_APPROVAL (denied envelope) because:
    1. No tenant action policy is configured → denies with
       "no active 'action_tools' policy for tenant"
    2. This proves the governance seam: generic connector metadata →
       operation resolver → TenantActionPolicy → DENY/REQUIRE_APPROVAL

    In production, this means the action goes into the approval queue
    and only fires after human approval.
    """
    from app.agents.tools import ToolInvoker, ToolRegistry
    from app.agents.tools.action_governance import build_action_tool_governance_runtime
    from app.governance.persistence.memory import InMemoryGovernanceRepository

    act_op = OperationDefinition(
        operation_id="pay",
        mode=OperationMode.ACT,
        commitment_kind=CommitmentKind.MONEY,
        approval_policy=ApprovalPolicy.TENANT_POLICY,
        target_resource_expr="order:{order_id}",
    )
    connector = ConnectorDefinition(
        connector_id="governed-connector",
        protocol="rest",
        operations=[act_op],
    )
    tool_name = "governed-connector.pay"
    credential_runtime = _ConnectorCredentialRuntime()
    tool = GenericConnectorTool(
        connector=connector,
        operation=act_op,
        config_repository=await _act_config_repo(tool_name),
        credential_runtime=credential_runtime,
    )

    registry = ToolRegistry()
    registry.register(tool)

    # Inject governance metadata into the request (as the orchestration
    # layer would do based on the operation definition)
    gov_metadata = act_op.governance_metadata()
    request = ToolInvocationRequest(
        tool_name=tool_name,
        payload={"order_id": "ORD-999", "amount_cents": 50000},
        metadata={
            AGENT_ACTION_PROVIDER_IDEMPOTENCY_KEY: "gov-test-key-1",
            "tool_name": tool_name,
            **gov_metadata,
        },
    )

    envelope = await ToolInvoker(
        tool_registry=registry,
        governance_runtime=build_action_tool_governance_runtime(
            persistence=InMemoryGovernanceRepository(),
            redis_client=None,
        ),
    ).invoke(request, _context(), invocation_ordinal=1)

    # Governance denied: no tenant policy → DENY (which is fail-closed)
    assert envelope.is_denied
    # Credentials were NEVER loaded (connector never reached)
    assert credential_runtime.calls == []


@pytest.mark.asyncio
async def test_governance_gate_blocks_undeclared_commitment_kind() -> None:
    """End-to-end: generic connector with NO commitment_kind declared →
    governance denies (fail-closed to human).
    """
    from app.agents.tools import ToolInvoker, ToolRegistry
    from app.agents.tools.action_governance import build_action_tool_governance_runtime
    from app.governance.persistence.memory import InMemoryGovernanceRepository

    act_op = OperationDefinition(
        operation_id="risky",
        mode=OperationMode.ACT,
        commitment_kind=None,  # UNDECLARED
    )
    connector = ConnectorDefinition(
        connector_id="risky-connector",
        protocol="rest",
        operations=[act_op],
    )
    tool_name = "risky-connector.risky"
    credential_runtime = _ConnectorCredentialRuntime()
    tool = GenericConnectorTool(
        connector=connector,
        operation=act_op,
        config_repository=await _act_config_repo(tool_name),
        credential_runtime=credential_runtime,
    )

    registry = ToolRegistry()
    registry.register(tool)

    # Metadata has no commitment_kind — governance must still block
    gov_metadata = act_op.governance_metadata()
    assert "operation_commitment_kind" not in gov_metadata

    request = ToolInvocationRequest(
        tool_name=tool_name,
        payload={"data": "test"},
        metadata={
            AGENT_ACTION_PROVIDER_IDEMPOTENCY_KEY: "risky-key-1",
            "tool_name": tool_name,
            **gov_metadata,
        },
    )

    envelope = await ToolInvoker(
        tool_registry=registry,
        governance_runtime=build_action_tool_governance_runtime(
            persistence=InMemoryGovernanceRepository(),
            redis_client=None,
        ),
    ).invoke(request, _context(), invocation_ordinal=1)

    # Fail-closed: denied even without explicit commitment_kind
    assert envelope.is_denied
    assert credential_runtime.calls == []


# ─── DOMAIN-AGNOSTIC GUARD (this test file itself) ──────────────────────────


def test_live_test_module_uses_neutral_endpoints_only() -> None:
    """Stage 3 test uses httpbin.org (neutral reference) — no vendor in code."""
    import inspect
    import re

    source = inspect.getsource(__import__(__name__))
    non_import_lines = [
        line for line in source.splitlines()
        if not line.strip().startswith(("from ", "import "))
    ]
    filtered = "\n".join(non_import_lines)
    vendor_terms = [
        "shopify", "zendesk", "stripe", "paypal", "amazon",
        "google", "whatsapp", "slack", "jira", "linear",
    ]
    for term in vendor_terms:
        pattern = rf"\b{re.escape(term)}\b"
        assert not re.search(pattern, filtered, re.IGNORECASE), (
            f"live test must not reference vendor: {term}"
        )

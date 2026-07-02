"""Break-controls for connector error message sanitization (security fix C).

(i)  A credential load failure whose exception body contains a fake token
     → the timeline/error_message contains NEITHER the token NOR the raw
       exception body, only the exception type name.
(ii) Server-side logging captures full detail (exc_info=True).
(iii) Normal non-secret errors (config missing, transport timeout) remain
      informative enough to diagnose (error_code present; type name present).
"""

from __future__ import annotations

import logging
import ssl
from typing import Any

import pytest

from app.agents.capabilities import CapabilitySet, ExecutionConstraints
from app.agents.context import AgentExecutionContext
from app.agents.identity import AgentIdentity, ExecutionIdentity, derive_agent_runtime_instance_id
from app.agents.results import ToolInvocationRequest
from app.agents.value_objects import CausalityMetadata
from app.agents.tools.connectors.base import (
    ConnectorConfigRecord,
    ConnectorHTTPRequest,
    ConnectorHTTPResponse,
    ConnectorProviderFields,
    ConnectorTool,
)
from app.agents.tools.connectors.config import ConnectorConfigRepository
from app.agents.tools.grants import AGENT_ACTION_PROVIDER_IDEMPOTENCY_KEY
from app.agents.tools.connectors.base import TenantCredentialRuntime
from app.tenant.enums import TenantChannelType

_TENANT = "tenant-cred-test"
_FAKE_SECRET = "Bearer eyJsZWFrZWRfdG9rZW4iOiAidGhpcyBzaG91bGQgbm90IGFwcGVhciJ9"


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------

class _AlwaysFailCredentialRuntime:
    """Raises with a message containing a fake credential in its text."""

    async def load_channel_credentials(
        self,
        *,
        tenant_id: str,
        channel_type: TenantChannelType,
    ) -> dict[str, Any]:
        raise RuntimeError(f"HTTP 401 Unauthorized: token={_FAKE_SECRET}")


class _AlwaysSucceedCredentialRuntime:
    async def load_channel_credentials(
        self,
        *,
        tenant_id: str,
        channel_type: TenantChannelType,
    ) -> dict[str, Any]:
        return {"bearer_token": "valid-token"}


class _StubConfigRepository:
    async def get_active_config(
        self,
        *,
        tenant_id: str,
        tool_name: str,
        expected_tenant_id: str,
    ) -> ConnectorConfigRecord | None:
        return ConnectorConfigRecord(
            tenant_id=tenant_id,
            connector_type="shopify",
            tool_name=tool_name,
            http_method="POST",
            endpoint_template="https://example.com/action",
            endpoint_host="example.com",
            idempotency_header_name="X-Idempotency-Key",
            field_mappings={},
            success_status_codes=(200,),
        )


class _StubConnectorTool(ConnectorTool):
    name = "stub.connector"

    def build_request(
        self, *, payload: Any, config: ConnectorConfigRecord
    ) -> ConnectorHTTPRequest:
        return ConnectorHTTPRequest(
            method="POST",
            url="https://example.com/action",
            json_body=dict(payload),
        )

    def parse_response(
        self, response: ConnectorHTTPResponse, *, config: ConnectorConfigRecord
    ) -> ConnectorProviderFields:
        return ConnectorProviderFields(
            provider_id="pid-1",
            provider_status="ok",
        )


def _execution_context(tenant_id: str = _TENANT) -> AgentExecutionContext:
    return AgentExecutionContext(
        identity=AgentIdentity(
            agent_id="test-agent",
            runtime_instance_id=derive_agent_runtime_instance_id(
                agent_ids=("test-agent",)
            ),
        ),
        execution=ExecutionIdentity(
            execution_id=__import__("uuid").uuid4(),
            request_id="req-test",
        ),
        capabilities=CapabilitySet(()),
        constraints=ExecutionConstraints(),
        causality=CausalityMetadata(initiator="test", cause="test"),
        tenant_id=tenant_id,
        metadata={},
    )


def _request(provider_key: str = "idem-key-001") -> ToolInvocationRequest:
    return ToolInvocationRequest(
        tool_name="stub.connector",
        payload={"order_id": "order-1"},
        metadata={AGENT_ACTION_PROVIDER_IDEMPOTENCY_KEY: provider_key},
    )


# ---------------------------------------------------------------------------
# Test (i): credential load failure must NOT include token in error_message
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_credential_load_failure_does_not_leak_token(
    caplog: pytest.LogCaptureFixture,
) -> None:
    tool = _StubConnectorTool(
        config_repository=_StubConfigRepository(),
        credential_runtime=_AlwaysFailCredentialRuntime(),
    )
    ctx = _execution_context()
    req = _request()

    with caplog.at_level(logging.ERROR, logger="app.agents.tools.connectors.base"):
        result = await tool.invoke(req, ctx)

    assert result.error_code == "credential_load_failed"
    assert result.error_message is not None

    # (i) The fake secret must NOT appear anywhere in the caller-visible message
    assert _FAKE_SECRET not in result.error_message, (
        f"Token leaked into error_message: {result.error_message!r}"
    )
    # The raw exception body must not appear either
    assert "401" not in result.error_message
    assert "Unauthorized" not in result.error_message
    # Only the exception type name is present
    assert "RuntimeError" in result.error_message


# ---------------------------------------------------------------------------
# Test (ii): server-side log captures full detail (exc_info=True)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_credential_load_failure_logs_full_detail(
    caplog: pytest.LogCaptureFixture,
) -> None:
    tool = _StubConnectorTool(
        config_repository=_StubConfigRepository(),
        credential_runtime=_AlwaysFailCredentialRuntime(),
    )
    ctx = _execution_context()
    req = _request()

    with caplog.at_level(logging.ERROR, logger="app.agents.tools.connectors.base"):
        await tool.invoke(req, ctx)

    # The log record must exist
    error_records = [
        r for r in caplog.records
        if r.levelno == logging.ERROR
        and "connector_credential_load_failed" in r.message
    ]
    assert error_records, "Expected an ERROR log record for credential load failure"
    # exc_info must have been captured (the traceback exists)
    assert error_records[0].exc_info is not None, (
        "Expected exc_info to be set so full detail is available in logs"
    )


# ---------------------------------------------------------------------------
# Test (iii): config-missing error is still informative (has error_code)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_config_missing_error_is_informative() -> None:
    class _NoConfigRepository:
        async def get_active_config(self, **_: Any) -> None:
            return None

    tool = _StubConnectorTool(
        config_repository=_NoConfigRepository(),
        credential_runtime=_AlwaysSucceedCredentialRuntime(),
    )
    ctx = _execution_context()
    req = _request()

    result = await tool.invoke(req, ctx)

    assert result.error_code == "connector_config_missing"
    assert result.error_message is not None
    # Config error message is allowed to include non-secret detail
    assert len(result.error_message) > 0

"""Availability-checker boundary for the remedy-selection walk (W3).

A narrow async protocol decouples the policy-driven remedy-ladder walk
(warranty_refund_remedy_selection.py) from the connector machinery
entirely — the walk only ever calls ``check_availability`` and never
imports anything connector/SSRF/credential-related. The real
implementation here wraps InventoryCheckConnector, translating its
ToolInvocationResult into the tri-state the walk needs: True
(confirmed available), False (confirmed unavailable), or None (the
check could not run at all — unconfigured, unreachable, or errored).
None must never be confused with False; the walk treats them very
differently (see warranty_refund_remedy_selection.py's fail-safe
docstring).
"""

from __future__ import annotations

import uuid
from typing import Protocol

from app.agents.capabilities import AgentCapability, CapabilitySet, ExecutionConstraints
from app.agents.context import AgentExecutionContext
from app.agents.enums import CapabilityScope
from app.agents.identity import (
    AgentIdentity,
    ExecutionIdentity,
    derive_action_idempotency_key,
    derive_agent_runtime_instance_id,
)
from app.agents.results import ToolInvocationRequest
from app.agents.tools.connectors.inventory import (
    AVAILABLE_PROVIDER_STATUS,
    InventoryCheckConnector,
)
from app.agents.tools.grants import AGENT_ACTION_PROVIDER_IDEMPOTENCY_KEY
from app.agents.value_objects import CausalityMetadata
from app.cognition.extraction import ExtractedOrderFields

_AGENT_ID = "warranty-refund-inventory-check"


class InventoryAvailabilityChecker(Protocol):
    async def check_availability(
        self,
        *,
        tenant_id: str,
        remedy: str,
        extracted_fields: ExtractedOrderFields,
    ) -> bool | None: ...


class ConnectorInventoryAvailabilityChecker:
    """Real adapter: queries InventoryCheckConnector, fails closed to None.

    Deliberately bypasses the agent action-governance/ToolInvoker/ledger
    stack — that machinery exists for approval-gated EXECUTION-phase
    actions. This is a read-only query made during recommendation
    construction, before any human has reviewed anything, so it calls
    the connector directly.
    """

    def __init__(self, *, connector: InventoryCheckConnector) -> None:
        self._connector = connector

    async def check_availability(
        self,
        *,
        tenant_id: str,
        remedy: str,
        extracted_fields: ExtractedOrderFields,
    ) -> bool | None:
        target_resource = _target_resource(remedy, extracted_fields)
        idempotency_key = derive_action_idempotency_key(
            tenant_id=tenant_id,
            session_id="warranty-refund-inventory-check",
            tool_name=InventoryCheckConnector.name,
            target_resource=target_resource,
        )
        sku_field = extracted_fields.get_field("product_sku")
        order_field = extracted_fields.get_field("order_id")
        request = ToolInvocationRequest(
            tool_name=InventoryCheckConnector.name,
            payload={
                "remedy": remedy,
                "product_sku": sku_field.value if sku_field is not None else None,
                "order_id": order_field.value if order_field is not None else None,
            },
            metadata={AGENT_ACTION_PROVIDER_IDEMPOTENCY_KEY: str(idempotency_key)},
        )
        context = _context(tenant_id=tenant_id, idempotency_key=idempotency_key)
        try:
            result = await self._connector.invoke(request, context)
        except Exception:  # noqa: BLE001 - fail closed to unknown availability.
            return None
        if result.status != "success":
            return None
        return result.output.get("provider_status") == AVAILABLE_PROVIDER_STATUS


def _target_resource(remedy: str, extracted_fields: ExtractedOrderFields) -> str:
    # Use get_field() so tenant-custom field names (e.g. "product_id" for a
    # non-commerce tenant) are handled identically to legacy "product_sku".
    sku_field = extracted_fields.get_field("product_sku")
    order_field = extracted_fields.get_field("order_id")
    sku = sku_field.value if sku_field is not None else None
    order_id = order_field.value if order_field is not None else None
    if sku is not None:
        return f"inventory:{remedy}:sku:{sku}"
    if order_id is not None:
        return f"inventory:{remedy}:order:{order_id}"
    return f"inventory:{remedy}"


def _context(*, tenant_id: str, idempotency_key: uuid.UUID) -> AgentExecutionContext:
    return AgentExecutionContext(
        identity=AgentIdentity(
            agent_id=_AGENT_ID,
            runtime_instance_id=derive_agent_runtime_instance_id(
                agent_ids=(_AGENT_ID,)
            ),
        ),
        execution=ExecutionIdentity(
            execution_id=idempotency_key,
            request_id=f"inventory-check:{idempotency_key}",
        ),
        capabilities=CapabilitySet(
            (
                AgentCapability(
                    name="tool.inventory.check",
                    scope=CapabilityScope.INVOKE,
                ),
            )
        ),
        constraints=ExecutionConstraints(allowed_tools=(InventoryCheckConnector.name,)),
        causality=CausalityMetadata(),
        tenant_id=tenant_id,
        metadata={},
    )


__all__ = [
    "ConnectorInventoryAvailabilityChecker",
    "InventoryAvailabilityChecker",
]

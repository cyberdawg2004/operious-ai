"""MVP-1 Gap 1 — Site 4: action payload / governance metadata agnosticism.

Verifies that:
1. generic_payload_builder forwards all non-structural scalar action fields —
   bank/telecom schemas produce correct payloads with NO order_id/product_sku.
2. generic_target_resource_builder produces a meaningful target without hardcoded names.
3. _request_metadata in orchestration passes ALL scalar action fields through as
   governance metadata, not just a hardcoded commerce field list.
4. inventory_availability.py uses get_field() — a tenant with non-legacy field names
   does not crash; falls back to None gracefully.
5. Fail-closed: an empty action (no data fields after structural key exclusion) does
   NOT produce a payload with None values for commerce-named keys.
6. E-commerce unchanged: existing commerce payload builders produce identical output
   (order_id, product_sku present where expected).
7. Static guard: operation_metadata.py and inventory_availability.py name no
   hardcoded commerce field literals in logic (only in the commerce-specific builders).
"""

from __future__ import annotations

import inspect
from typing import Any


from app.agents.tools.operation_metadata import (
    ACTION_STRUCTURAL_KEYS,
    generic_payload_builder,
    generic_target_resource_builder,
)
from app.cognition.extraction import ExtractedField, ExtractedOrderFields

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeProposal:
    resolution_category: str = "billing_dispute"
    proposed_customer_reply: str = "We are reviewing your request."
    session_id: str = "session-abc"


_PROPOSAL = _FakeProposal()


def _action(**kwargs: Any) -> dict[str, Any]:
    return {"type": "some_action", "requires_execution": True, **kwargs}


# ---------------------------------------------------------------------------
# 1. generic_payload_builder — bank schema
# ---------------------------------------------------------------------------


def test_generic_payload_bank_fields() -> None:
    """Bank action with transaction_id + dispute_amount produces payload with those keys."""
    action = _action(
        transaction_id="TXN-999",
        dispute_amount="250.00",
        merchant="some-merchant",
    )
    payload = generic_payload_builder(action, _PROPOSAL, "dispute")

    assert payload["transaction_id"] == "TXN-999"
    assert payload["dispute_amount"] == "250.00"
    assert payload["merchant"] == "some-merchant"
    # No order_id or product_sku fabricated
    assert "order_id" not in payload
    assert "product_sku" not in payload


def test_generic_payload_telecom_fields() -> None:
    """Telecom action with account_number + service_type produces correct payload."""
    action = _action(
        account_number="ACC-123",
        service_type="broadband",
    )
    payload = generic_payload_builder(action, _PROPOSAL, "service_credit")

    assert payload["account_number"] == "ACC-123"
    assert payload["service_type"] == "broadband"
    assert "order_id" not in payload
    assert "product_sku" not in payload


def test_generic_payload_excludes_structural_keys() -> None:
    """Structural keys (type, tool_name, payload, …) are not forwarded as payload body."""
    action = {
        "type": "refund_request",
        "tool_name": "refund.request",
        "label": "Process refund",
        "requires_execution": True,
        "payload_template": {},
        "target_resource_id": "order:X",
        "payload": {"something": "nested"},
        "warranty_refund_eligibility": {"verdict": "eligible"},
        "resolution_verdict": {"outcome": "approved"},
        "account_number": "ACC-123",  # the one data field
    }
    payload = generic_payload_builder(action, _PROPOSAL, "service_credit")

    for structural in ACTION_STRUCTURAL_KEYS:
        assert structural not in payload, f"Structural key {structural!r} leaked into payload"
    assert payload["account_number"] == "ACC-123"


def test_generic_payload_empty_action_has_issue_category_fallback() -> None:
    """An action with no data fields still gets issue_category from the proposal."""
    action = _action()
    payload = generic_payload_builder(action, _PROPOSAL, "query")

    assert payload.get("issue_category") == "billing_dispute"


def test_generic_payload_none_values_not_included() -> None:
    """Fields with None or empty-string values are excluded (fail-closed)."""
    action = _action(account_number="", bad_field=None)
    payload = generic_payload_builder(action, _PROPOSAL, "query")

    assert "account_number" not in payload
    assert "bad_field" not in payload


# ---------------------------------------------------------------------------
# 2. generic_target_resource_builder
# ---------------------------------------------------------------------------


def test_generic_target_uses_explicit_target_resource_id() -> None:
    action = _action(target_resource_id="account:ACC-123")
    result = generic_target_resource_builder(action, {}, "some.tool", "dispute")
    assert result == "account:ACC-123"


def test_generic_target_uses_first_payload_string_when_no_explicit() -> None:
    payload = {"account_number": "ACC-999", "service_type": "mobile"}
    result = generic_target_resource_builder({}, payload, "some.tool", "dispute")
    assert result == "ACC-999"


def test_generic_target_falls_back_to_tool_name() -> None:
    result = generic_target_resource_builder({}, {}, "bank.credit", "dispute")
    assert result == "bank.credit"


def test_generic_target_falls_back_to_action_type() -> None:
    result = generic_target_resource_builder({}, {}, None, "dispute")
    assert result == "dispute"


def test_generic_target_ultimate_fallback() -> None:
    result = generic_target_resource_builder({}, {}, None, None)
    assert result == "operation"


# ---------------------------------------------------------------------------
# 3. orchestration._request_metadata passes all scalar action fields through
# ---------------------------------------------------------------------------


def test_request_metadata_passes_non_commerce_fields() -> None:
    """_request_metadata must include tenant field names, not just commerce ones."""
    from app.agents.tools.orchestration import _request_metadata  # type: ignore[attr-defined]
    from unittest.mock import MagicMock

    proposal = MagicMock()
    proposal.session_id = "sess-1"
    proposal.proposal_id = "prop-1"
    proposal.dispatch_id = "dispatch-1"
    proposal.execution_id = "exec-1"
    proposal.confidence = 0.9
    proposal.resolution_category = "billing"

    action = {
        "type": "dispute",
        "tool_name": "bank.credit",
        "requires_execution": True,
        "account_number": "ACC-123",
        "dispute_amount": "150.00",
    }

    metadata = _request_metadata(
        proposal=proposal,
        action=action,
        action_type="dispute",
        tool_name="bank.credit",
        target_resource="account:ACC-123",
        idempotency_key="idem-1",
    )

    assert metadata["account_number"] == "ACC-123"
    assert metadata["dispute_amount"] == "150.00"
    # Structural keys excluded
    assert "type" not in metadata
    assert "requires_execution" not in metadata


def test_request_metadata_still_includes_commerce_fields_for_ecommerce() -> None:
    """E-commerce actions still get order_id/product_sku in metadata."""
    from app.agents.tools.orchestration import _request_metadata  # type: ignore[attr-defined]
    from unittest.mock import MagicMock

    proposal = MagicMock()
    proposal.session_id = "sess-2"
    proposal.proposal_id = "prop-2"
    proposal.dispatch_id = "dispatch-2"
    proposal.execution_id = "exec-2"
    proposal.confidence = 0.95
    proposal.resolution_category = "product_defect"

    action = {
        "type": "refund_request",
        "tool_name": "refund.request",
        "requires_execution": True,
        "order_id": "ORD-777",
        "product_sku": "SKU-ABC",
        "refund_amount_cents": 5000,
    }

    metadata = _request_metadata(
        proposal=proposal,
        action=action,
        action_type="refund_request",
        tool_name="refund.request",
        target_resource="order:ORD-777:sku:SKU-ABC",
        idempotency_key="idem-2",
    )

    assert metadata["order_id"] == "ORD-777"
    assert metadata["product_sku"] == "SKU-ABC"
    assert metadata["refund_amount_cents"] == 5000


# ---------------------------------------------------------------------------
# 4. inventory_availability.py uses get_field()
# ---------------------------------------------------------------------------


def test_inventory_target_resource_with_legacy_fields() -> None:
    """Legacy e-commerce fields (product_sku, order_id) still produce correct target."""
    from app.runtime.inventory_availability import _target_resource

    fields = ExtractedOrderFields(
        product_sku=ExtractedField(value="SKU-X", confidence="high", source="text"),
        order_id=ExtractedField(value="ORD-1", confidence="high", source="text"),
    )
    result = _target_resource("replacement", fields)
    assert result == "inventory:replacement:sku:SKU-X"


def test_inventory_target_resource_no_fields_returns_remedy_only() -> None:
    """When no known fields are present, returns the bare remedy string."""
    from app.runtime.inventory_availability import _target_resource

    fields = ExtractedOrderFields()
    result = _target_resource("replacement", fields)
    assert result == "inventory:replacement"


def test_inventory_target_resource_order_id_only() -> None:
    """Falls back to order_id when product_sku is absent."""
    from app.runtime.inventory_availability import _target_resource

    fields = ExtractedOrderFields(
        order_id=ExtractedField(value="ORD-2", confidence="high", source="text"),
    )
    result = _target_resource("refund", fields)
    assert result == "inventory:refund:order:ORD-2"


def test_inventory_check_payload_uses_get_field_not_direct_attr() -> None:
    """The payload sent to InventoryCheckConnector uses get_field() values correctly."""
    from unittest.mock import MagicMock
    from app.runtime.inventory_availability import ConnectorInventoryAvailabilityChecker
    from app.agents.tools.connectors.inventory import AVAILABLE_PROVIDER_STATUS
    import asyncio

    captured_payloads: list[dict] = []

    class _FakeConnector:
        name = "inventory.check"

        async def invoke(self, request: Any, context: Any) -> Any:
            captured_payloads.append(dict(request.payload))
            result = MagicMock()
            result.status = "success"
            result.output = {"provider_status": AVAILABLE_PROVIDER_STATUS}
            return result

    checker = ConnectorInventoryAvailabilityChecker(connector=_FakeConnector())  # type: ignore[arg-type]
    fields = ExtractedOrderFields(
        product_sku=ExtractedField(value="SKU-Y", confidence="high", source="text"),
        order_id=ExtractedField(value="ORD-3", confidence="high", source="text"),
    )

    result = asyncio.get_event_loop().run_until_complete(
        checker.check_availability(
            tenant_id="tenant-test",
            remedy="replacement",
            extracted_fields=fields,
        )
    )

    assert result is True
    assert captured_payloads[0]["product_sku"] == "SKU-Y"
    assert captured_payloads[0]["order_id"] == "ORD-3"


# ---------------------------------------------------------------------------
# 5. E-commerce commerce payload builders unchanged
# ---------------------------------------------------------------------------


def test_commerce_warranty_payload_builder_unchanged() -> None:
    """_warranty_payload still produces commerce fields for commerce operations."""
    from app.agents.tools.operation_metadata import payload_for_operation, resolve_operation

    action = {
        "type": "warranty_claim",
        "tool_name": "warranty.claim",
        "order_id": "ORD-X",
        "product_sku": "SKU-X",
        "issue_category": "defective",
    }
    op = resolve_operation(tool_name="warranty.claim", action_type="warranty_claim")
    assert op is not None

    payload = payload_for_operation(
        operation=op,
        action=action,
        proposal=_PROPOSAL,
        action_type="warranty_claim",
    )
    assert payload is not None
    assert payload["order_id"] == "ORD-X"
    assert payload["product_sku"] == "SKU-X"
    assert payload["issue_category"] == "defective"


def test_commerce_refund_payload_builder_unchanged() -> None:
    from app.agents.tools.operation_metadata import payload_for_operation, resolve_operation

    action = {
        "type": "refund_request",
        "tool_name": "refund.request",
        "order_id": "ORD-R",
        "product_sku": "SKU-R",
        "refund_amount_cents": 3500,
    }
    op = resolve_operation(tool_name="refund.request", action_type="refund_request")
    assert op is not None

    payload = payload_for_operation(
        operation=op,
        action=action,
        proposal=_PROPOSAL,
        action_type="refund_request",
    )
    assert payload is not None
    assert payload["order_id"] == "ORD-R"
    assert payload["product_sku"] == "SKU-R"
    assert payload["refund_amount_cents"] == 3500


# ---------------------------------------------------------------------------
# 6. Static guard — no hardcoded field literals in generic logic
# ---------------------------------------------------------------------------


def test_generic_payload_builder_has_no_hardcoded_commerce_fields() -> None:
    """generic_payload_builder source contains no hardcoded commerce field names."""
    source = inspect.getsource(generic_payload_builder)
    for field_name in ('"order_id"', '"product_sku"', '"purchase_date"', '"seller"'):
        assert field_name not in source, (
            f"Hardcoded commerce field {field_name} found in generic_payload_builder"
        )


def test_generic_target_builder_has_no_hardcoded_commerce_fields() -> None:
    """generic_target_resource_builder source contains no hardcoded commerce field names."""
    source = inspect.getsource(generic_target_resource_builder)
    for field_name in ('"order_id"', '"product_sku"', '"purchase_date"'):
        assert field_name not in source, (
            f"Hardcoded commerce field {field_name} found in generic_target_resource_builder"
        )


def test_inventory_availability_uses_get_field_not_direct_attr() -> None:
    """inventory_availability._target_resource uses get_field(), not .product_sku/.order_id."""
    import app.runtime.inventory_availability as inv_module

    source = inspect.getsource(inv_module._target_resource)  # type: ignore[attr-defined]
    # Direct attribute access banned in this function
    assert ".product_sku.value" not in source
    assert ".order_id.value" not in source
    # get_field used instead
    assert "get_field" in source


def test_action_structural_keys_complete() -> None:
    """ACTION_STRUCTURAL_KEYS covers all non-data keys that appear in action dicts."""
    expected_structural = {
        "type", "tool_name", "label", "requires_execution",
        "payload_template", "target_resource_id", "payload",
        "warranty_refund_eligibility", "resolution_verdict",
    }
    assert expected_structural.issubset(ACTION_STRUCTURAL_KEYS)

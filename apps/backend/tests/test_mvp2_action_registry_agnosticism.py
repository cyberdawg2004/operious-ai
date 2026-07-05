"""MVP-2: Generic Action Registry agnosticism tests.

Goal: prove that non-commerce tenants (bank, telecom, insurance) can register
their own action tool names and have them governed identically to the e-commerce
commerce tools — without modifying Python source code.

Tests:
1. Custom tool declared in action_tools policy → accepted, commitment_kind injected
2. Custom tool with commitment_kind=money → REQUIRE_APPROVAL (money/goods gate)
3. Custom tool with decision=allow + commitment_kind=none → ALLOW
4. Custom tool with decision=deny → DENY
5. Missing commitment_kind in custom tool declaration → ActionPolicyParseError
6. Unknown tool_name (not declared in policy) → REQUIRE_APPROVAL (fail-closed)
7. Custom-only policy (no registered ops) → parses without requiring commerce tools
8. Mixed policy (registered + custom) → both are parsed and work
9. resolution_taxonomy accepts non-commerce tool_name in recommended_actions
10. TenantConnectorRegistry resolves tool names from connector config
11. Static guard: resolution_taxonomy_policy no longer imports KNOWN_ACTION_TOOL_NAMES
12. Domain-agnostic: bank schema "account.credit" + telecom "service.ticket" both
    thread through the same policy parse path
"""

from __future__ import annotations

import inspect
from datetime import datetime, timezone
from typing import Any

import pytest

from app.agents.tools.action_governance import (
    ACTION_TOOLS_POLICY_TYPE,
    ActionPolicyParseError,
    TenantActionPolicy,
    parse_action_tools_policy,
    validate_action_tools_policy_parameters,
)
from app.agents.tools.operation_metadata import CommitmentKind
from app.agents.tools.registry import TenantConnectorRegistry
from app.governance.enums import Decision
from app.tenant.chronology import canonical_sha256
from app.tenant.enums import TenantGovernancePolicyStatus
from app.tenant.identity import derive_governance_policy_version_id
from app.tenant.persistence import (
    InMemoryTenantConfigurationRepository,
    TenantGovernancePolicyRecord,
)


_NOW = datetime(2026, 7, 3, tzinfo=timezone.utc)
_TENANT = "tenant-mvp2-bank"
_APPROVAL_ID = "approval-mvp2"
_APPROVED_BY = "policy-admin"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _policy_record(
    *,
    tenant_id: str = _TENANT,
    parameters: dict[str, Any],
    version: int = 1,
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


def _custom_only_policy(
    tools: dict[str, Any],
    tenant_id: str = _TENANT,
) -> TenantGovernancePolicyRecord:
    return _policy_record(
        tenant_id=tenant_id,
        parameters={"tools": tools},
    )


def _commerce_policy_parameters() -> dict[str, Any]:
    """Full e-commerce action_tools policy — all 4 required registered ops."""
    return {
        "phase": "2.4",
        "tools": {
            "warranty.claim": {
                "allow": {
                    "confidence_gte": 0.85,
                    "issue_category_in": ["charging_issue"],
                },
                "else": "require_approval",
            },
            "replacement.order": {"always": "require_approval"},
            "refund.request": {
                "allow": {"refund_amount_cents_lte": 5000},
                "else": "require_approval",
            },
            "warehouse.repair.report": {
                "allow": {"severity_in": ["low"]},
                "require_approval": {"severity_in": ["high", "critical"]},
            },
        },
    }


# ---------------------------------------------------------------------------
# 1. Custom tool declared in policy → commitment_kind present in parsed policy
# ---------------------------------------------------------------------------


def test_custom_only_policy_parses_bank_tool() -> None:
    """A bank tenant declaring only 'account.credit' must parse without error."""
    record = _custom_only_policy({
        "account.credit": {
            "commitment_kind": "money",
            "decision": "require_approval",
        }
    })
    policy = parse_action_tools_policy(record)
    assert "account.credit" in policy.custom_tools
    decl = policy.custom_tools["account.credit"]
    assert decl.commitment_kind == CommitmentKind.MONEY
    assert decl.decision == Decision.REQUIRE_APPROVAL


def test_custom_only_policy_parses_telecom_tool() -> None:
    """A telecom tenant declaring 'service.ticket' must parse without error."""
    record = _custom_only_policy({
        "service.ticket": {
            "commitment_kind": "record_update",
            "decision": "allow",
        }
    })
    policy = parse_action_tools_policy(record)
    assert "service.ticket" in policy.custom_tools
    decl = policy.custom_tools["service.ticket"]
    assert decl.commitment_kind == CommitmentKind.RECORD_UPDATE
    assert decl.decision == Decision.ALLOW


def test_custom_tool_commitment_kind_none() -> None:
    """'none' is a valid commitment_kind (no money/goods commitment)."""
    record = _custom_only_policy({
        "info.query": {
            "commitment_kind": "none",
            "decision": "allow",
        }
    })
    policy = parse_action_tools_policy(record)
    assert policy.custom_tools["info.query"].commitment_kind == CommitmentKind.NONE


def test_custom_tool_commitment_kind_goods() -> None:
    """'goods' commitment_kind is valid for custom tools."""
    record = _custom_only_policy({
        "device.replace": {
            "commitment_kind": "goods",
            "decision": "require_approval",
        }
    })
    policy = parse_action_tools_policy(record)
    assert policy.custom_tools["device.replace"].commitment_kind == CommitmentKind.GOODS


# ---------------------------------------------------------------------------
# 2. Missing commitment_kind → fail-closed ActionPolicyParseError
# ---------------------------------------------------------------------------


def test_custom_tool_missing_commitment_kind_raises() -> None:
    """A custom tool without commitment_kind must be rejected at parse time.

    commitment_kind drives the INVIOLABLE money/goods gate. A dangling
    custom tool without it cannot be safely governed.
    """
    record = _custom_only_policy({
        "account.credit": {
            # commitment_kind absent
            "decision": "require_approval",
        }
    })
    with pytest.raises(ActionPolicyParseError, match="commitment_kind"):
        parse_action_tools_policy(record)


def test_custom_tool_empty_commitment_kind_raises() -> None:
    record = _custom_only_policy({
        "account.credit": {
            "commitment_kind": "",
            "decision": "require_approval",
        }
    })
    with pytest.raises(ActionPolicyParseError, match="commitment_kind"):
        parse_action_tools_policy(record)


def test_custom_tool_invalid_commitment_kind_raises() -> None:
    record = _custom_only_policy({
        "account.credit": {
            "commitment_kind": "free_money",
            "decision": "require_approval",
        }
    })
    with pytest.raises(ActionPolicyParseError, match="commitment_kind"):
        parse_action_tools_policy(record)


# ---------------------------------------------------------------------------
# 3. Custom-only policy: no registered commerce ops required
# ---------------------------------------------------------------------------


def test_custom_only_policy_does_not_require_refund_request() -> None:
    """A bank tenant with custom tools should NOT be required to declare
    warranty.claim, refund.request, replacement.order, warehouse.repair.report.
    """
    # This must NOT raise ActionPolicyParseError("missing required tool rule(s)")
    validate_action_tools_policy_parameters({
        "tools": {
            "account.credit": {
                "commitment_kind": "money",
                "decision": "require_approval",
            },
            "account.debit": {
                "commitment_kind": "money",
                "decision": "deny",
            },
        }
    })


def test_custom_only_policy_multiple_tools() -> None:
    """Multiple custom tools all parse correctly."""
    validate_action_tools_policy_parameters({
        "tools": {
            "insurance.claim": {"commitment_kind": "money", "decision": "require_approval"},
            "policy.update": {"commitment_kind": "record_update", "decision": "allow"},
            "coverage.query": {"commitment_kind": "none", "decision": "allow"},
        }
    })


# ---------------------------------------------------------------------------
# 4. Mixed policy: registered + custom tools both work
# ---------------------------------------------------------------------------


def test_mixed_policy_parses_both_registered_and_custom() -> None:
    """A tenant using some registered ops + a custom tool must satisfy required
    registered ops AND parse the custom tool.
    """
    params = dict(_commerce_policy_parameters())
    params["tools"]["account.credit"] = {
        "commitment_kind": "money",
        "decision": "require_approval",
    }
    record = _policy_record(parameters=params)
    policy = parse_action_tools_policy(record)

    # Registered ops still work
    assert "operation.refund_request" in policy.rules
    assert "operation.warranty_claim" in policy.rules

    # Custom tool also parsed
    assert "account.credit" in policy.custom_tools
    assert policy.custom_tools["account.credit"].commitment_kind == CommitmentKind.MONEY


# ---------------------------------------------------------------------------
# 5. TenantActionPolicy.evaluate() — custom tool governance
# ---------------------------------------------------------------------------


async def _evaluate_custom_tool_governance(
    *,
    tool_name: str,
    policy_tools: dict[str, Any],
    tenant_id: str = _TENANT,
) -> Decision:
    """Helper: evaluate governance for a custom tool invocation."""
    from app.governance.context import GovernanceContext
    from app.governance.subjects.agent_actions import AgentActionGovernanceSubject
    from app.governance.enums import EnforcementStage
    from app.identity import TenantId

    repository = InMemoryTenantConfigurationRepository()
    record = _custom_only_policy(policy_tools, tenant_id=tenant_id)
    await repository.save_governance_policy(record, expected_tenant_id=tenant_id)

    policy_instance = TenantActionPolicy(repository=repository)

    subject = AgentActionGovernanceSubject(
        tool_name=tool_name,
        tenant_id=tenant_id,
        metadata={
            "tool_name": tool_name,
            "action_type": tool_name.replace(".", "_"),
        },
    )
    context = GovernanceContext(
        stage=EnforcementStage.PRE_EXECUTION,
        action=f"tool.{tool_name}",
        resource=f"tool:{tool_name}",
        tenant_id=TenantId(tenant_id),
        subject=subject,
    )
    results = await policy_instance.evaluate(context)
    assert results
    return results[0].decision


async def test_custom_tool_require_approval_decision() -> None:
    """Custom tool with decision=require_approval → REQUIRE_APPROVAL."""
    decision = await _evaluate_custom_tool_governance(
        tool_name="account.credit",
        policy_tools={
            "account.credit": {
                "commitment_kind": "money",
                "decision": "require_approval",
            }
        },
    )
    assert decision == Decision.REQUIRE_APPROVAL


async def test_custom_tool_deny_decision() -> None:
    """Custom tool with commitment_kind=money + decision=deny → REQUIRE_APPROVAL.

    Post security-fix behavior: money/goods commitment_kind always routes to
    REQUIRE_APPROVAL regardless of the tenant's declared decision field.
    The inviolable gate fires before the decision check.
    A non-committing tool with decision=deny would return DENY.
    """
    decision = await _evaluate_custom_tool_governance(
        tool_name="account.debit",
        policy_tools={
            "account.debit": {
                "commitment_kind": "money",
                "decision": "deny",
            }
        },
    )
    # Security fix: money/goods → always REQUIRE_APPROVAL, not DENY
    assert decision == Decision.REQUIRE_APPROVAL


async def test_custom_noncommitting_tool_deny_decision() -> None:
    """A non-committing custom tool with decision=deny → DENY (as declared)."""
    decision = await _evaluate_custom_tool_governance(
        tool_name="info.query",
        policy_tools={
            "info.query": {
                "commitment_kind": "none",
                "decision": "deny",
            }
        },
    )
    assert decision == Decision.DENY


async def test_custom_tool_allow_decision() -> None:
    """Custom tool with decision=allow + commitment_kind=none → ALLOW."""
    decision = await _evaluate_custom_tool_governance(
        tool_name="info.query",
        policy_tools={
            "info.query": {
                "commitment_kind": "none",
                "decision": "allow",
            }
        },
    )
    assert decision == Decision.ALLOW


async def test_unknown_tool_name_require_approval_fail_closed() -> None:
    """A tool_name not declared in the policy → REQUIRE_APPROVAL (fail-closed).

    Non-declared tools are never silently allowed. This preserves the
    invariant that every tool execution requires an explicit policy declaration.
    """
    decision = await _evaluate_custom_tool_governance(
        tool_name="undeclared.tool",
        policy_tools={
            "account.credit": {
                "commitment_kind": "money",
                "decision": "require_approval",
            }
        },
    )
    assert decision == Decision.REQUIRE_APPROVAL


# ---------------------------------------------------------------------------
# 6. resolution_taxonomy accepts non-commerce tool_name
# ---------------------------------------------------------------------------


def test_resolution_taxonomy_accepts_bank_tool_name() -> None:
    """resolution_taxonomy policy now accepts any non-empty tool_name.

    Previously: only KNOWN_ACTION_TOOL_NAMES were accepted.
    Now: any non-empty string is accepted; the governance gate at runtime
    validates the tool against the tenant's action_tools policy.
    """
    from app.runtime.resolution_taxonomy_policy import (
        validate_resolution_taxonomy_policy_parameters,
    )

    validate_resolution_taxonomy_policy_parameters({
        "categories": [
            {
                "id": "billing_dispute",
                "label": "Billing Dispute",
                "description": "Customer has a billing dispute",
                "recommended_actions": [
                    {
                        "type": "credit_account",
                        "label": "Credit the account",
                        "requires_execution": True,
                        "tool_name": "account.credit",        # NOT in KNOWN_ACTION_TOOL_NAMES
                        "payload_template": {"amount": "{amount}"},
                        "target_resource_id": "account:{account_number}",
                    }
                ],
            }
        ],
    })


def test_resolution_taxonomy_accepts_telecom_tool_name() -> None:
    from app.runtime.resolution_taxonomy_policy import (
        validate_resolution_taxonomy_policy_parameters,
    )

    validate_resolution_taxonomy_policy_parameters({
        "categories": [
            {
                "id": "service_outage",
                "label": "Service Outage",
                "description": "Service is down",
                "recommended_actions": [
                    {
                        "type": "ticket_service",
                        "label": "Raise a service ticket",
                        "requires_execution": True,
                        "tool_name": "service.ticket",        # NOT in KNOWN_ACTION_TOOL_NAMES
                        "payload_template": {},
                        "target_resource_id": "service:{account_number}",
                    }
                ],
            }
        ],
    })


def test_resolution_taxonomy_still_accepts_commerce_tool_names() -> None:
    """E-commerce tool names continue to work — backward compatibility."""
    from app.runtime.resolution_taxonomy_policy import (
        validate_resolution_taxonomy_policy_parameters,
    )

    validate_resolution_taxonomy_policy_parameters({
        "categories": [
            {
                "id": "product_defect",
                "label": "Product Defect",
                "description": "Defective product",
                "recommended_actions": [
                    {
                        "type": "refund_request",
                        "label": "Process refund",
                        "requires_execution": True,
                        "tool_name": "refund.request",       # still accepted
                        "payload_template": {},
                        "target_resource_id": "order:{order_id}",
                    }
                ],
            }
        ],
    })


# ---------------------------------------------------------------------------
# 7. TenantConnectorRegistry resolves tool names from connector config
# ---------------------------------------------------------------------------


async def _save_connector_config(
    repo: InMemoryTenantConfigurationRepository,
    *,
    tenant_id: str,
    tool_name: str,
    status: str = "active",
) -> None:
    """Helper: save a minimal connector configuration record."""
    from app.tenant.persistence.records import TenantConnectorConfigurationRecord
    import hashlib

    sha = hashlib.sha256(f"{tenant_id}:{tool_name}:v1".encode()).hexdigest()
    record = TenantConnectorConfigurationRecord(
        tenant_id=tenant_id,
        connector_type="generic",
        tool_name=tool_name,
        http_method="POST",
        endpoint_template="https://api.example.com/v1",
        endpoint_host="api.example.com",
        field_mappings={},
        idempotency_header_name="Idempotency-Key",
        response_parse={},
        success_status_codes=(200,),
        status=status,
        version=1,
        configured_by="admin",
        source_approval_id="approval-test",
        content_sha256=sha,
        previous_version_sha256=None,
        created_at=_NOW,
        updated_at=_NOW,
    )
    await repo.save_connector_configuration(record, expected_tenant_id=tenant_id)


async def test_tenant_connector_registry_resolves_active_tools() -> None:
    """TenantConnectorRegistry returns tool_names for active connectors."""
    repo = InMemoryTenantConfigurationRepository()
    await _save_connector_config(repo, tenant_id=_TENANT, tool_name="account.credit")
    await _save_connector_config(repo, tenant_id=_TENANT, tool_name="account.debit")

    registry = TenantConnectorRegistry(repository=repo)  # type: ignore[arg-type]
    tool_names = await registry.resolve(tenant_id=_TENANT)

    assert "account.credit" in tool_names
    assert "account.debit" in tool_names


async def test_tenant_connector_registry_tenant_isolation() -> None:
    """Registry must not return tool names from a different tenant."""
    repo = InMemoryTenantConfigurationRepository()
    await _save_connector_config(repo, tenant_id="tenant-other", tool_name="other.tool")

    registry = TenantConnectorRegistry(repository=repo)  # type: ignore[arg-type]
    tool_names = await registry.resolve(tenant_id=_TENANT)

    assert "other.tool" not in tool_names
    assert len(tool_names) == 0


async def test_tenant_connector_registry_empty_when_no_connectors() -> None:
    registry = TenantConnectorRegistry(
        repository=InMemoryTenantConfigurationRepository()  # type: ignore[arg-type]
    )
    tool_names = await registry.resolve(tenant_id=_TENANT)
    assert tool_names == frozenset()


# ---------------------------------------------------------------------------
# 8. Static guard: resolution_taxonomy_policy no longer imports KNOWN_ACTION_TOOL_NAMES
# ---------------------------------------------------------------------------


def test_taxonomy_policy_does_not_import_known_action_tool_names() -> None:
    """resolution_taxonomy_policy.py must NOT import KNOWN_ACTION_TOOL_NAMES.

    This import was the mechanism by which the taxonomy validator blocked
    non-commerce tool names. It has been removed as part of MVP-2.
    Confirmed by inspecting the module's imported names.
    """
    import app.runtime.resolution_taxonomy_policy as taxonomy_module

    source = inspect.getsource(taxonomy_module)
    assert "KNOWN_ACTION_TOOL_NAMES" not in source, (
        "resolution_taxonomy_policy.py must not import or reference "
        "KNOWN_ACTION_TOOL_NAMES — non-commerce tool names must be accepted"
    )


# ---------------------------------------------------------------------------
# 9. Domain-agnostic: bank + telecom schemas thread through same policy parse
# ---------------------------------------------------------------------------


def test_bank_and_telecom_tools_parse_through_same_code_path() -> None:
    """Prove domain-agnosticism: completely different vertical tool names
    parse through the same _parse_custom_tool_declaration code path.
    """
    bank_record = _custom_only_policy(
        {
            "account.credit": {"commitment_kind": "money", "decision": "require_approval"},
            "chargeback.initiate": {"commitment_kind": "money", "decision": "require_approval"},
            "account.query": {"commitment_kind": "none", "decision": "allow"},
        },
        tenant_id="bank-tenant",
    )
    telecom_record = _custom_only_policy(
        {
            "service.ticket": {"commitment_kind": "record_update", "decision": "allow"},
            "plan.upgrade": {"commitment_kind": "goods", "decision": "require_approval"},
            "sim.replace": {"commitment_kind": "goods", "decision": "require_approval"},
        },
        tenant_id="telecom-tenant",
    )
    insurance_record = _custom_only_policy(
        {
            "claim.initiate": {"commitment_kind": "money", "decision": "require_approval"},
            "policy.renew": {"commitment_kind": "money", "decision": "require_approval"},
            "coverage.query": {"commitment_kind": "none", "decision": "allow"},
        },
        tenant_id="insurance-tenant",
    )

    bank_policy = parse_action_tools_policy(bank_record)
    telecom_policy = parse_action_tools_policy(telecom_record)
    insurance_policy = parse_action_tools_policy(insurance_record)

    # All custom tools parsed
    assert len(bank_policy.custom_tools) == 3
    assert len(telecom_policy.custom_tools) == 3
    assert len(insurance_policy.custom_tools) == 3

    # Commitment kinds correctly parsed
    assert bank_policy.custom_tools["account.credit"].commitment_kind == CommitmentKind.MONEY
    assert telecom_policy.custom_tools["service.ticket"].commitment_kind == CommitmentKind.RECORD_UPDATE
    assert insurance_policy.custom_tools["coverage.query"].commitment_kind == CommitmentKind.NONE

    # No cross-contamination between tenants
    assert "account.credit" not in telecom_policy.custom_tools
    assert "service.ticket" not in bank_policy.custom_tools


# ---------------------------------------------------------------------------
# 10. E-commerce backward compatibility: existing tests / behavior preserved
# ---------------------------------------------------------------------------


def test_commerce_policy_still_requires_registered_ops_when_using_them() -> None:
    """An e-commerce tenant that uses registered ops still requires all 4."""
    # Partially declared registered ops → should still fail
    with pytest.raises(ActionPolicyParseError, match="missing required tool rule"):
        validate_action_tools_policy_parameters({
            "tools": {
                "warranty.claim": {
                    "allow": {"confidence_gte": 0.85, "issue_category_in": ["x"]},
                    "else": "require_approval",
                },
                # Missing: replacement.order, refund.request, warehouse.repair.report
            }
        })


def test_commerce_policy_full_parameters_still_valid() -> None:
    """The existing full e-commerce action_tools policy remains valid."""
    validate_action_tools_policy_parameters(_commerce_policy_parameters())


def test_commerce_and_custom_tools_require_registered_ops_when_mixed() -> None:
    """A mixed policy that declares at least one registered op must have
    all required registered ops declared."""
    with pytest.raises(ActionPolicyParseError, match="missing required tool rule"):
        validate_action_tools_policy_parameters({
            "tools": {
                "warranty.claim": {
                    "allow": {"confidence_gte": 0.85, "issue_category_in": ["x"]},
                    "else": "require_approval",
                },
                "account.credit": {
                    "commitment_kind": "money",
                    "decision": "require_approval",
                },
                # refund.request, replacement.order, warehouse.repair.report still required
            }
        })

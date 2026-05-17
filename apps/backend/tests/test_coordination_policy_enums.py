"""Coordination-policy enum vocabulary — pinned wire-format values.

Any rename / reorder / value-change here is a breaking change to
every previously persisted policy record and the test catalogue
surfaces it at import time. Same discipline as
`tests/test_coordination_enums.py`.
"""

from __future__ import annotations

from app.coordination.policy.enums import (
    CoordinationEscalationType,
    CoordinationPolicyDecision,
    CoordinationPolicyScope,
    CoordinationRestrictionType,
)


_DECISION_WIRE_VALUES: dict[CoordinationPolicyDecision, str] = {
    CoordinationPolicyDecision.ALLOW: "allow",
    CoordinationPolicyDecision.ANNOTATE: "annotate",
    CoordinationPolicyDecision.RESTRICT: "restrict",
    CoordinationPolicyDecision.ESCALATE: "escalate",
    CoordinationPolicyDecision.DENY: "deny",
}

_SCOPE_WIRE_VALUES: dict[CoordinationPolicyScope, str] = {
    CoordinationPolicyScope.SENDER: "sender",
    CoordinationPolicyScope.RECIPIENT: "recipient",
    CoordinationPolicyScope.DIRECTION: "direction",
    CoordinationPolicyScope.MESSAGE_TYPE: "message_type",
    CoordinationPolicyScope.TOPOLOGY: "topology",
    CoordinationPolicyScope.TENANT: "tenant",
    CoordinationPolicyScope.ESCALATION: "escalation",
    CoordinationPolicyScope.GLOBAL: "global",
}

_RESTRICTION_WIRE_VALUES: dict[CoordinationRestrictionType, str] = {
    CoordinationRestrictionType.SENDER_RESTRICTION: "sender_restriction",
    CoordinationRestrictionType.RECIPIENT_RESTRICTION: "recipient_restriction",
    CoordinationRestrictionType.DIRECTION_RESTRICTION: "direction_restriction",
    CoordinationRestrictionType.TENANT_RESTRICTION: "tenant_restriction",
    CoordinationRestrictionType.MESSAGE_TYPE_RESTRICTION: "message_type_restriction",
    CoordinationRestrictionType.PRIORITY_CAP: "priority_cap",
    CoordinationRestrictionType.METADATA_REDACTION: "metadata_redaction",
    CoordinationRestrictionType.AUDIT_AMPLIFICATION: "audit_amplification",
}

_ESCALATION_WIRE_VALUES: dict[CoordinationEscalationType, str] = {
    CoordinationEscalationType.HUMAN_REVIEW: "human_review",
    CoordinationEscalationType.TENANT_OWNER_APPROVAL: "tenant_owner_approval",
    CoordinationEscalationType.CROSS_TENANT_AUTHORITY: "cross_tenant_authority",
    CoordinationEscalationType.SUPERVISOR_NOTIFICATION: "supervisor_notification",
    CoordinationEscalationType.GOVERNANCE_ESCALATION: "governance_escalation",
    CoordinationEscalationType.OPERATIONAL_REVIEW: "operational_review",
}


def test_policy_decision_values_pinned() -> None:
    for member, expected in _DECISION_WIRE_VALUES.items():
        assert member.value == expected


def test_policy_decision_set_matches() -> None:
    assert set(CoordinationPolicyDecision) == set(
        _DECISION_WIRE_VALUES.keys()
    )


def test_policy_scope_values_pinned() -> None:
    for member, expected in _SCOPE_WIRE_VALUES.items():
        assert member.value == expected


def test_policy_scope_set_matches() -> None:
    assert set(CoordinationPolicyScope) == set(_SCOPE_WIRE_VALUES.keys())


def test_restriction_type_values_pinned() -> None:
    for member, expected in _RESTRICTION_WIRE_VALUES.items():
        assert member.value == expected


def test_restriction_type_set_matches() -> None:
    assert set(CoordinationRestrictionType) == set(
        _RESTRICTION_WIRE_VALUES.keys()
    )


def test_escalation_type_values_pinned() -> None:
    for member, expected in _ESCALATION_WIRE_VALUES.items():
        assert member.value == expected


def test_escalation_type_set_matches() -> None:
    assert set(CoordinationEscalationType) == set(
        _ESCALATION_WIRE_VALUES.keys()
    )


def test_policy_decision_str_round_trip() -> None:
    for member in CoordinationPolicyDecision:
        assert CoordinationPolicyDecision(member.value) is member


def test_policy_scope_str_round_trip() -> None:
    for member in CoordinationPolicyScope:
        assert CoordinationPolicyScope(member.value) is member


def test_restriction_type_str_round_trip() -> None:
    for member in CoordinationRestrictionType:
        assert CoordinationRestrictionType(member.value) is member


def test_escalation_type_str_round_trip() -> None:
    for member in CoordinationEscalationType:
        assert CoordinationEscalationType(member.value) is member

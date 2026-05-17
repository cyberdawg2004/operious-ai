"""Canonical built-in finding-code + evidence-metadata-key vocabulary.

Sprint K hardening — names the codes / keys the built-in evaluators
emit so renames and typos surface at import time instead of as
silent drift in audit dashboards.

This module is a **vocabulary discipline aid**, not a schema
enforcement layer:

* `RuntimeFinding.code` remains a plain `str` for wire-stability,
* `EvaluationEvidence.metadata` remains `Mapping[str, Any]` for
  deployment-specific extensibility,
* `StrEnum` members flow transparently into string contexts
  (`finding.code == FindingCode.EXECUTION_FAILED` works in both
  directions),
* external evaluators may emit codes outside this catalogue — the
  taxonomy is the canonical *built-in* set, not a closed universe.

Adding a new builtin finding type → add an entry here. The pinned
`tests/test_supervisor_hardening.py` catalogue invariants flag
unannounced changes.
"""

from __future__ import annotations

from enum import StrEnum


class FindingCode(StrEnum):
    """Stable codes emitted by the built-in supervisor evaluators."""

    # ─── ExecutionCompletionEvaluator ────────────────────────────────
    EXECUTION_FAILED = "execution.failed"
    EXECUTION_CANCELLED = "execution.cancelled"
    EXECUTION_INCOMPLETE = "execution.incomplete"

    # ─── ToolInvocationEvaluator ─────────────────────────────────────
    TOOL_DENIED = "tool.denied"
    TOOL_FAILED = "tool.failed"

    # ─── GovernanceComplianceEvaluator ───────────────────────────────
    GOVERNANCE_DENY = "governance.deny"
    GOVERNANCE_ESCALATE = "governance.escalate"
    GOVERNANCE_REQUIRE_APPROVAL = "governance.require_approval"
    GOVERNANCE_DEGRADE = "governance.degrade"
    GOVERNANCE_REDACT = "governance.redact"
    # Prefix only — concrete codes are formed by appending the unknown
    # verdict value (e.g. ``governance.unknown.foo``) so audit tools
    # see the offending verdict in the code itself.
    GOVERNANCE_UNKNOWN_PREFIX = "governance.unknown"

    # ─── StateMachineHealthEvaluator ─────────────────────────────────
    STATE_MACHINE_ILLEGAL_TRANSITION = "state_machine.illegal_transition"


class EvidenceMetadataKey(StrEnum):
    """Canonical keys built-in evaluators write into evidence metadata.

    Naming the keys here is the discipline boundary —
    `EvaluationEvidence.metadata` itself stays free-form
    `Mapping[str, Any]` so deployment- and tenant-specific keys
    remain possible. The vocabulary here is the *recommended* shape
    for join-able audit fields.
    """

    POLICY_CHAIN_ID = "policy_chain_id"
    STAGE = "stage"
    VIOLATION_COUNT = "violation_count"
    TOOL_NAME = "tool_name"
    DECISION = "decision"


__all__ = ["FindingCode", "EvidenceMetadataKey"]

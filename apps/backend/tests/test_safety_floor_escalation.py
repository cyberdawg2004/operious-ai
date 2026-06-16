"""Break-control tests for the safety-floor P0/CRISIS escalation.

These tests prove the guarantee: a physical-hazard ticket (swollen battery,
smoking, fire…) ALWAYS creates a P0/CRISIS escalation record — regardless of
what the LLM returns as the resolution_category.  The escalation is created in
the worker independently of the proposal's governance verdict.

Why these tests exist
─────────────────────
Production incident: a "swollen power bank" ticket was auto-sent with NO human
escalation because the LLM classified it as ``charging_issue``.  The governance
gate only blocks on a hard `_SAFETY_KEYWORDS` list, which did not include
single-word tokens like "swollen".  The safety floor (`_SAFETY_FLOOR_KEYWORDS`)
was added to catch these cases at the worker level.

Break-control invariant
───────────────────────
If ``resolution_contains_safety_floor_keywords`` is removed or returns False for
a hazard word, the positive assertion below fails → the regression is caught
before it ships.
"""

from __future__ import annotations

import unittest.mock
import uuid

import pytest

from app.governance.enums import Decision
from app.governance.persistence import InMemoryGovernanceRepository
from app.runtime.resolution_runtime import resolution_contains_safety_floor_keywords
from app.workers.agent_tasks import (  # private but importable for tests
    _DiagnosticExecutionWorkItem,
    _SAFETY_FLOOR_POLICY_CHAIN_ID,
    _resolve_safety_floor_escalation_governance_decision_id,
)

# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────

_TENANT = "ten_breakctl_test"
_SESSION = "ses_breakctl_test"

_SWOLLEN_BATTERY_CONTENT = (
    "My power bank is swollen and feels hot to the touch. "
    "It won't charge and the casing looks puffy. Please help."
)

_SAFE_CONTENT = "My PowerCore stopped charging after a firmware update."


def _work_item(content: str) -> _DiagnosticExecutionWorkItem:
    return _DiagnosticExecutionWorkItem(
        execution_id=str(uuid.uuid4()),
        attempt_id=str(uuid.uuid4()),
        attempt_number=1,
        dispatch_id=str(uuid.uuid4()),
        session_id=_SESSION,
        tenant_id=_TENANT,
        content=content,
    )


# ────────────────────────────────────────────────────────────────────────────
# Keyword detection table
# ────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        "my power bank is swollen and hot",
        "battery is swollen",
        "swollen power bank",
        "the case is splitting open and it feels hot",
        "bulging battery",
        "it's smoking",
        "battery caught fire",
        "puffy battery",
        "leaking battery",
    ],
)
def test_hazard_keyword_detection_returns_true(text: str) -> None:
    """Every physical-hazard phrase must return True — no false negatives."""
    assert resolution_contains_safety_floor_keywords(text) is True


# ────────────────────────────────────────────────────────────────────────────
# Break-control: escalation IS created for a miscategorised swollen-battery
# ────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_safety_floor_creates_crisis_escalation_despite_charging_issue_category() -> None:
    """P0 escalation is created even when the LLM returns charging_issue.

    This is the EXACT production failure scenario.  The LLM category is
    irrelevant to the floor — it only looks at raw inbound content.
    """
    governance_repo = InMemoryGovernanceRepository()
    work_item = _work_item(_SWOLLEN_BATTERY_CONTENT)

    # The content simulates the LLM having classified this as "charging_issue"
    # at high confidence — but the floor must fire regardless because "swollen"
    # and "hot" are in _SAFETY_FLOOR_KEYWORDS.

    decision_id = await _resolve_safety_floor_escalation_governance_decision_id(
        governance_repo=governance_repo,  # type: ignore[arg-type]
        work_item=work_item,
    )

    # ── A decision_id must be returned (not None) ──
    assert decision_id is not None, (
        "Floor returned None for swollen-battery content — escalation NOT created. "
        "This is the production failure mode: P0 hazard ticket auto-resolves."
    )

    # ── The governance record must be stored ──
    record = await governance_repo.get_decision(
        decision_id, expected_tenant_id=_TENANT
    )
    assert record is not None, "Governance decision record was not persisted"

    # ── Must be an ESCALATE decision, not DENY ──
    assert record.decision == Decision.ESCALATE.value, (
        f"Expected ESCALATE, got {record.decision!r}"
    )

    # ── Must use the safety-floor policy chain ──
    assert record.policy_chain_id == _SAFETY_FLOOR_POLICY_CHAIN_ID

    # ── Must have exactly one violation with the crisis. prefix ──
    assert len(record.violations) == 1
    violation = record.violations[0]
    assert violation.policy_name.startswith("crisis."), (
        f"Violation policy_name must start with 'crisis.' for CRISIS handoff kind; "
        f"got {violation.policy_name!r}"
    )

    # ── Severity must be 100 (P0) ──
    assert violation.severity == 100, f"Expected severity 100, got {violation.severity}"


# ────────────────────────────────────────────────────────────────────────────
# Negative control: removing the floor check means no escalation
# ────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_negative_control_removing_floor_check_prevents_escalation() -> None:
    """BREAK-CONTROL: patch the keyword function to False → no escalation.

    This proves the safety floor is what catches the miscategorised case.
    If something else were creating the escalation, removing the floor would
    still return a decision_id — but it must not.

    Removing ``resolution_contains_safety_floor_keywords`` from the worker
    (or changing it to always return False) MUST flip this test to FAIL
    in the positive assertion above — which is what this test proves.
    """
    governance_repo = InMemoryGovernanceRepository()
    work_item = _work_item(_SWOLLEN_BATTERY_CONTENT)

    with unittest.mock.patch(
        "app.workers.agent_tasks.resolution_contains_safety_floor_keywords",
        return_value=False,
    ):
        decision_id = await _resolve_safety_floor_escalation_governance_decision_id(
            governance_repo=governance_repo,  # type: ignore[arg-type]
            work_item=work_item,
        )

    assert decision_id is None, (
        "Without the floor check, no escalation should be created. "
        "If decision_id is not None here, something other than the floor "
        "is triggering the escalation — investigate."
    )
    assert governance_repo._decisions == {}, (
        "Governance repo must be empty when floor check is disabled"
    )


# ────────────────────────────────────────────────────────────────────────────
# Safe content must NOT create an escalation
# ────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_safe_content_does_not_trigger_floor_escalation() -> None:
    """Non-hazard content must not create an escalation record (no false alarm)."""
    governance_repo = InMemoryGovernanceRepository()
    work_item = _work_item(_SAFE_CONTENT)

    decision_id = await _resolve_safety_floor_escalation_governance_decision_id(
        governance_repo=governance_repo,  # type: ignore[arg-type]
        work_item=work_item,
    )

    assert decision_id is None
    assert governance_repo._decisions == {}


# ────────────────────────────────────────────────────────────────────────────
# Idempotency: retry must not duplicate the governance record
# ────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_floor_escalation_is_idempotent_on_retry() -> None:
    """Calling the function twice for the same session must not raise or duplicate."""
    governance_repo = InMemoryGovernanceRepository()
    work_item = _work_item(_SWOLLEN_BATTERY_CONTENT)

    decision_id_1 = await _resolve_safety_floor_escalation_governance_decision_id(
        governance_repo=governance_repo,  # type: ignore[arg-type]
        work_item=work_item,
    )
    # Second call (simulating Celery retry)
    decision_id_2 = await _resolve_safety_floor_escalation_governance_decision_id(
        governance_repo=governance_repo,  # type: ignore[arg-type]
        work_item=work_item,
    )

    assert decision_id_1 == decision_id_2, "Deterministic UUID5 must be stable across calls"
    assert len(governance_repo._decisions) == 1, "No duplicate record on retry"

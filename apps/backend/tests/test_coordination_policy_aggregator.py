"""`build_policy_decision` — pure precedence aggregator.

Precedence: DENY > ESCALATE > RESTRICT > ANNOTATE > ALLOW.
Most-restrictive wins. Restrictions / escalations carry forward
only from findings whose decision matches the apex verdict.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.coordination.policy.enums import (
    CoordinationEscalationType,
    CoordinationPolicyDecision,
    CoordinationPolicyScope,
    CoordinationRestrictionType,
)
from app.coordination.policy.models.escalation import (
    CoordinationPolicyEscalation,
)
from app.coordination.policy.models.findings import (
    CoordinationPolicyFinding,
)
from app.coordination.policy.models.restriction import (
    CoordinationPolicyRestriction,
)
from app.coordination.policy.runtime.aggregator import (
    build_policy_decision,
)
from app.coordination.policy.taxonomy import (
    coordination_policy_precedence,
    is_allow_policy_decision,
    is_blocking_policy_decision,
)


def _finding(
    decision: CoordinationPolicyDecision,
    *,
    restrictions: tuple[CoordinationPolicyRestriction, ...] = (),
    escalations: tuple[CoordinationPolicyEscalation, ...] = (),
) -> CoordinationPolicyFinding:
    return CoordinationPolicyFinding(
        finding_id=uuid4(),
        evaluator_name="test",
        scope=CoordinationPolicyScope.TOPOLOGY,
        decision=decision,
        code=f"test.{decision.value}",
        message="t",
        restrictions=restrictions,
        escalations=escalations,
        detected_at=datetime.now(timezone.utc),
    )


def test_empty_findings_default_to_allow() -> None:
    apex, restrictions, escalations, reason = build_policy_decision(())
    assert apex is CoordinationPolicyDecision.ALLOW
    assert restrictions == ()
    assert escalations == ()
    assert "no findings" in reason


def test_deny_dominates_over_lower_severity() -> None:
    findings = (
        _finding(CoordinationPolicyDecision.ALLOW),
        _finding(CoordinationPolicyDecision.RESTRICT),
        _finding(CoordinationPolicyDecision.DENY),
    )
    apex, _, _, _ = build_policy_decision(findings)
    assert apex is CoordinationPolicyDecision.DENY


def test_escalate_dominates_over_restrict() -> None:
    findings = (
        _finding(CoordinationPolicyDecision.RESTRICT),
        _finding(CoordinationPolicyDecision.ESCALATE),
    )
    apex, _, _, _ = build_policy_decision(findings)
    assert apex is CoordinationPolicyDecision.ESCALATE


def test_restrict_dominates_over_annotate_and_allow() -> None:
    findings = (
        _finding(CoordinationPolicyDecision.ALLOW),
        _finding(CoordinationPolicyDecision.ANNOTATE),
        _finding(CoordinationPolicyDecision.RESTRICT),
    )
    apex, _, _, _ = build_policy_decision(findings)
    assert apex is CoordinationPolicyDecision.RESTRICT


def test_restrictions_aggregate_only_from_matching_decision() -> None:
    cap = CoordinationPolicyRestriction(
        kind=CoordinationRestrictionType.PRIORITY_CAP,
        target="agent:planner",
    )
    redact = CoordinationPolicyRestriction(
        kind=CoordinationRestrictionType.METADATA_REDACTION,
        target="agent:planner",
    )
    findings = (
        _finding(
            CoordinationPolicyDecision.RESTRICT, restrictions=(cap,)
        ),
        # Annotate-level restriction should NOT bubble up:
        _finding(
            CoordinationPolicyDecision.ANNOTATE, restrictions=(redact,)
        ),
    )
    apex, restrictions, _, _ = build_policy_decision(findings)
    assert apex is CoordinationPolicyDecision.RESTRICT
    assert restrictions == (cap,)


def test_escalations_aggregate_only_from_matching_decision() -> None:
    esc = CoordinationPolicyEscalation(
        kind=CoordinationEscalationType.HUMAN_REVIEW
    )
    findings = (
        _finding(CoordinationPolicyDecision.RESTRICT),
        _finding(
            CoordinationPolicyDecision.ESCALATE, escalations=(esc,)
        ),
    )
    apex, restrictions, escalations, _ = build_policy_decision(findings)
    assert apex is CoordinationPolicyDecision.ESCALATE
    assert escalations == (esc,)
    # Restrict-level restrictions don't carry — apex is ESCALATE.
    assert restrictions == ()


# ─── Precedence + blocking helpers ────────────────────────────────────


def test_precedence_is_monotonic() -> None:
    ordered = sorted(
        CoordinationPolicyDecision, key=coordination_policy_precedence
    )
    assert ordered == [
        CoordinationPolicyDecision.DENY,
        CoordinationPolicyDecision.ESCALATE,
        CoordinationPolicyDecision.RESTRICT,
        CoordinationPolicyDecision.ANNOTATE,
        CoordinationPolicyDecision.ALLOW,
    ]


def test_is_blocking_policy_decision_pinned() -> None:
    assert is_blocking_policy_decision(CoordinationPolicyDecision.DENY)
    assert is_blocking_policy_decision(
        CoordinationPolicyDecision.ESCALATE
    )
    assert not is_blocking_policy_decision(
        CoordinationPolicyDecision.RESTRICT
    )
    assert not is_blocking_policy_decision(
        CoordinationPolicyDecision.ANNOTATE
    )
    assert not is_blocking_policy_decision(
        CoordinationPolicyDecision.ALLOW
    )


def test_is_allow_policy_decision_only_allow() -> None:
    assert is_allow_policy_decision(CoordinationPolicyDecision.ALLOW)
    for non in (
        CoordinationPolicyDecision.ANNOTATE,
        CoordinationPolicyDecision.RESTRICT,
        CoordinationPolicyDecision.ESCALATE,
        CoordinationPolicyDecision.DENY,
    ):
        assert not is_allow_policy_decision(non)

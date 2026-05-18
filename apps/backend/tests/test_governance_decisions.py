"""Sprint I — decision-builder determinism tests.

Pins the aggregation contract:

* `build_decision` is the SINGLE place precedence is applied,
* same evaluation results → byte-identical decision (modulo decision_id +
  decided_at, which the caller supplies for replay),
* most-restrictive verdict wins; precedence is total-ordered,
* `violations` includes every non-ALLOW result, not just winning class,
* `restrictions` carries only winning-class restrictions,
* the precedence order is the documented one:
  DENY > REQUIRE_APPROVAL > ESCALATE > DEGRADE > REDACT > ALLOW.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.governance.decisions import (
    PolicyEvaluationResult,
    build_decision,
)
from app.governance.enums import (
    Decision,
    EnforcementStage,
    RestrictionKind,
    ViolationSeverity,
)
from app.governance.value_objects import RuntimeRestriction


def _result(
    decision: Decision,
    *,
    policy: str = "p",
    rule: str = "r",
    severity: ViolationSeverity = ViolationSeverity.LOW,
    restrictions: tuple[RuntimeRestriction, ...] = (),
) -> PolicyEvaluationResult:
    return PolicyEvaluationResult(
        policy_name=policy,
        rule_id=rule,
        decision=decision,
        severity=severity,
        reason="t",
        restrictions=restrictions,
    )


def _restriction(
    *,
    policy: str = "p",
    rule: str = "r",
    target: str = "foo",
) -> RuntimeRestriction:
    return RuntimeRestriction(
        kind=RestrictionKind.MODEL_RESTRICTION,
        target=target,
        value="value",
        reason="r",
        policy_name=policy,
        rule_id=rule,
    )


# ─── Precedence tests ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "results, expected",
    [
        ([Decision.ALLOW], Decision.ALLOW),
        ([Decision.ALLOW, Decision.REDACT], Decision.REDACT),
        ([Decision.REDACT, Decision.DEGRADE], Decision.DEGRADE),
        ([Decision.DEGRADE, Decision.ESCALATE], Decision.ESCALATE),
        ([Decision.ESCALATE, Decision.REQUIRE_APPROVAL], Decision.REQUIRE_APPROVAL),
        ([Decision.REQUIRE_APPROVAL, Decision.DENY], Decision.DENY),
        # Multi-way: DENY beats everything
        (
            [Decision.ALLOW, Decision.REDACT, Decision.DEGRADE, Decision.DENY],
            Decision.DENY,
        ),
        # Multi-way without DENY: REQUIRE_APPROVAL wins
        (
            [Decision.ALLOW, Decision.REDACT, Decision.REQUIRE_APPROVAL],
            Decision.REQUIRE_APPROVAL,
        ),
    ],
)
def test_precedence_is_total_ordered(
    results: list[Decision], expected: Decision
) -> None:
    decision = build_decision(
        stage=EnforcementStage.PRE_RETRIEVAL,
        policy_chain_id="chain.test",
        evaluation_results=tuple(_result(d) for d in results),
    )
    assert decision.decision is expected


def test_empty_results_synthesize_fail_closed_deny() -> None:
    """Constitutional Core Law 4 (Governance Determinism): empty
    evaluation results MUST fail closed. The substrate synthesises a
    DENY result so the operation is refused rather than silently
    permitted — `no_governance_evaluated` is the canonical
    attribution."""
    decision = build_decision(
        stage=EnforcementStage.PRE_RETRIEVAL,
        policy_chain_id="chain.test",
        evaluation_results=(),
    )
    assert decision.decision is Decision.DENY
    assert len(decision.evaluated_rules) == 1
    assert (
        decision.evaluated_rules[0].rule_id
        == "no_governance_evaluated"
    )
    assert (
        decision.evaluated_rules[0].policy_name
        == "governance.substrate"
    )
    assert len(decision.violations) == 1
    assert decision.violations[0].rule_id == "no_governance_evaluated"
    assert decision.restrictions == ()


# ─── Violation extraction ─────────────────────────────────────────────


def test_violations_include_every_non_allow_result() -> None:
    results = (
        _result(Decision.ALLOW, policy="p1", rule="r1"),
        _result(Decision.REDACT, policy="p2", rule="r2"),
        _result(Decision.DENY, policy="p3", rule="r3"),
    )
    decision = build_decision(
        stage=EnforcementStage.PRE_RETRIEVAL,
        policy_chain_id="chain.test",
        evaluation_results=results,
    )
    assert len(decision.violations) == 2
    violation_rules = {(v.policy_name, v.rule_id) for v in decision.violations}
    assert violation_rules == {("p2", "r2"), ("p3", "r3")}


def test_violations_preserve_input_order() -> None:
    results = (
        _result(Decision.REDACT, policy="b", rule="r1"),
        _result(Decision.DENY, policy="a", rule="r2"),
        _result(Decision.REDACT, policy="c", rule="r3"),
    )
    decision = build_decision(
        stage=EnforcementStage.PRE_RETRIEVAL,
        policy_chain_id="chain.test",
        evaluation_results=results,
    )
    assert [v.policy_name for v in decision.violations] == ["b", "a", "c"]


# ─── Restriction extraction ───────────────────────────────────────────


def test_restrictions_come_only_from_winning_class_results() -> None:
    redact_r = _restriction(policy="r_pol")
    degrade_r = _restriction(policy="d_pol")
    results = (
        _result(
            Decision.REDACT,
            policy="r_pol",
            rule="r",
            restrictions=(redact_r,),
        ),
        _result(
            Decision.DEGRADE,
            policy="d_pol",
            rule="r",
            restrictions=(degrade_r,),
        ),
    )
    decision = build_decision(
        stage=EnforcementStage.PRE_RETRIEVAL,
        policy_chain_id="chain.test",
        evaluation_results=results,
    )
    # DEGRADE is more restrictive than REDACT → final is DEGRADE,
    # only degrade restrictions carry forward.
    assert decision.decision is Decision.DEGRADE
    assert decision.restrictions == (degrade_r,)


def test_restrictions_aggregate_across_winning_class_results() -> None:
    r1 = _restriction(target="model:a")
    r2 = _restriction(target="model:b")
    results = (
        _result(Decision.DEGRADE, rule="r1", restrictions=(r1,)),
        _result(Decision.DEGRADE, rule="r2", restrictions=(r2,)),
    )
    decision = build_decision(
        stage=EnforcementStage.PRE_RETRIEVAL,
        policy_chain_id="chain.test",
        evaluation_results=results,
    )
    assert decision.restrictions == (r1, r2)


# ─── Determinism + replay ─────────────────────────────────────────────


def test_decision_is_byte_identical_for_fixed_input_and_id() -> None:
    fixed_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    fixed_ts = datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc)
    results = (
        _result(Decision.REDACT, policy="p1", rule="r1"),
        _result(Decision.ALLOW, policy="p2", rule="r2"),
    )
    a = build_decision(
        stage=EnforcementStage.PRE_RETRIEVAL,
        policy_chain_id="chain.test",
        evaluation_results=results,
        decision_id=fixed_id,
        decided_at=fixed_ts,
    )
    b = build_decision(
        stage=EnforcementStage.PRE_RETRIEVAL,
        policy_chain_id="chain.test",
        evaluation_results=results,
        decision_id=fixed_id,
        decided_at=fixed_ts,
    )
    assert a == b


# ─── Reason composition ───────────────────────────────────────────────


def test_reason_attributes_to_winning_rules() -> None:
    results = (
        _result(Decision.REDACT, policy="p1", rule="r1"),
        _result(Decision.DENY, policy="p2", rule="r2"),
        _result(Decision.DENY, policy="p3", rule="r3"),
    )
    decision = build_decision(
        stage=EnforcementStage.PRE_RETRIEVAL,
        policy_chain_id="chain.test",
        evaluation_results=results,
    )
    assert decision.decision is Decision.DENY
    # Reason includes both winning DENY rules, but not the REDACT rule.
    assert "p2.r2" in decision.reason
    assert "p3.r3" in decision.reason
    assert "p1.r1" not in decision.reason


def test_allow_reason_is_stable() -> None:
    decision = build_decision(
        stage=EnforcementStage.PRE_RETRIEVAL,
        policy_chain_id="chain.test",
        evaluation_results=(_result(Decision.ALLOW),),
    )
    assert decision.reason == "all rules allowed"


# ─── is_allow / is_blocking accessors ────────────────────────────────


def test_is_allow_only_true_for_allow_decision() -> None:
    allow = build_decision(
        stage=EnforcementStage.PRE_RETRIEVAL,
        policy_chain_id="c",
        evaluation_results=(_result(Decision.ALLOW),),
    )
    deny = build_decision(
        stage=EnforcementStage.PRE_RETRIEVAL,
        policy_chain_id="c",
        evaluation_results=(_result(Decision.DENY),),
    )
    assert allow.is_allow
    assert not deny.is_allow


def test_is_blocking_for_deny_require_approval_escalate() -> None:
    for d in (Decision.DENY, Decision.REQUIRE_APPROVAL, Decision.ESCALATE):
        dec = build_decision(
            stage=EnforcementStage.PRE_RETRIEVAL,
            policy_chain_id="c",
            evaluation_results=(_result(d),),
        )
        assert dec.is_blocking, f"{d.value} should block"
    for d in (Decision.DEGRADE, Decision.REDACT, Decision.ALLOW):
        dec = build_decision(
            stage=EnforcementStage.PRE_RETRIEVAL,
            policy_chain_id="c",
            evaluation_results=(_result(d),),
        )
        assert not dec.is_blocking, f"{d.value} should NOT block"

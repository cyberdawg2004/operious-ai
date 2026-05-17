"""Taxonomy invariants for the arbitration substrate.

* Authority precedence pins the canonical hierarchy.
* Verdict classification helpers behave consistently.
* Contradiction / cross-axis tables are symmetric.
"""

from __future__ import annotations

from app.arbitration.enums import (
    ArbitrationAuthorityLevel,
    ArbitrationVerdictKind,
)
from app.arbitration.taxonomy import (
    arbitration_authority_precedence,
    compare_authority,
    is_authorisation_verdict,
    is_contradiction,
    is_cross_axis_contradiction,
    is_higher_authority,
    is_quality_verdict,
)


def test_authority_precedence_pinned() -> None:
    assert (
        arbitration_authority_precedence(
            ArbitrationAuthorityLevel.GOVERNANCE
        )
        == 0
    )
    assert (
        arbitration_authority_precedence(
            ArbitrationAuthorityLevel.TOPOLOGY
        )
        == 1
    )
    assert (
        arbitration_authority_precedence(
            ArbitrationAuthorityLevel.POLICY
        )
        == 2
    )
    assert (
        arbitration_authority_precedence(
            ArbitrationAuthorityLevel.ARBITRATION
        )
        == 3
    )
    assert (
        arbitration_authority_precedence(
            ArbitrationAuthorityLevel.SUPERVISOR
        )
        == 4
    )
    assert (
        arbitration_authority_precedence(
            ArbitrationAuthorityLevel.EXECUTION
        )
        == 5
    )


def test_is_higher_authority_implies_lower_precedence_number() -> None:
    levels = list(ArbitrationAuthorityLevel)
    for a in levels:
        for b in levels:
            if a is b:
                continue
            higher = is_higher_authority(a, b)
            assert higher is (
                arbitration_authority_precedence(a)
                < arbitration_authority_precedence(b)
            )


def test_compare_authority_is_signed_difference() -> None:
    gov = ArbitrationAuthorityLevel.GOVERNANCE
    sup = ArbitrationAuthorityLevel.SUPERVISOR
    assert compare_authority(gov, sup) < 0
    assert compare_authority(sup, gov) > 0
    assert compare_authority(gov, gov) == 0


def test_arbitration_self_authority_strictly_lower_than_governance() -> None:
    """Arbitration's OWN authority is strictly LOWER than governance.

    This is the structural guarantee that arbitration cannot override
    higher authority.
    """
    assert is_higher_authority(
        ArbitrationAuthorityLevel.GOVERNANCE,
        ArbitrationAuthorityLevel.ARBITRATION,
    )
    assert is_higher_authority(
        ArbitrationAuthorityLevel.TOPOLOGY,
        ArbitrationAuthorityLevel.ARBITRATION,
    )
    assert is_higher_authority(
        ArbitrationAuthorityLevel.POLICY,
        ArbitrationAuthorityLevel.ARBITRATION,
    )


def test_verdict_classification_partitions_known_axes() -> None:
    auth = {
        v
        for v in ArbitrationVerdictKind
        if is_authorisation_verdict(v)
    }
    quality = {
        v for v in ArbitrationVerdictKind if is_quality_verdict(v)
    }
    assert auth & quality == set()
    assert ArbitrationVerdictKind.ALLOW in auth
    assert ArbitrationVerdictKind.DENY in auth
    assert ArbitrationVerdictKind.PASS in quality
    assert ArbitrationVerdictKind.FAIL in quality


def test_contradiction_table_is_symmetric() -> None:
    for a in ArbitrationVerdictKind:
        for b in ArbitrationVerdictKind:
            assert is_contradiction(a, b) is is_contradiction(b, a)
            assert is_cross_axis_contradiction(
                a, b
            ) is is_cross_axis_contradiction(b, a)


def test_known_contradiction_pairs() -> None:
    assert is_contradiction(
        ArbitrationVerdictKind.ALLOW, ArbitrationVerdictKind.DENY
    )
    assert is_contradiction(
        ArbitrationVerdictKind.PASS, ArbitrationVerdictKind.FAIL
    )
    assert is_contradiction(
        ArbitrationVerdictKind.SAFE, ArbitrationVerdictKind.UNSAFE
    )
    assert is_contradiction(
        ArbitrationVerdictKind.VALID, ArbitrationVerdictKind.INVALID
    )
    assert is_contradiction(
        ArbitrationVerdictKind.ALLOW,
        ArbitrationVerdictKind.ESCALATE,
    )
    assert not is_contradiction(
        ArbitrationVerdictKind.PASS, ArbitrationVerdictKind.SAFE
    )
    assert not is_contradiction(
        ArbitrationVerdictKind.WARN, ArbitrationVerdictKind.PASS
    )


def test_cross_axis_pairs() -> None:
    assert is_cross_axis_contradiction(
        ArbitrationVerdictKind.ALLOW, ArbitrationVerdictKind.UNSAFE
    )
    assert is_cross_axis_contradiction(
        ArbitrationVerdictKind.DENY, ArbitrationVerdictKind.SAFE
    )
    assert not is_cross_axis_contradiction(
        ArbitrationVerdictKind.ALLOW, ArbitrationVerdictKind.SAFE
    )

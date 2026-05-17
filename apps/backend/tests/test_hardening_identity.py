"""Verify replay-safe deterministic identity derivation."""

from __future__ import annotations

import pytest

from app.hardening.identity import (
    derive_audit_id,
    derive_boundary_id,
    derive_correlation_id,
    derive_dependency_audit_id,
    derive_failure_record_id,
    derive_finding_id,
    derive_trace_id,
    derive_violation_id,
    generate_audit_id,
    generate_correlation_id,
    generate_finding_id,
    generate_trace_id,
)


def test_derive_audit_id_is_deterministic() -> None:
    assert derive_audit_id(seed="abc") == derive_audit_id(
        seed="abc"
    )
    assert derive_audit_id(seed="abc") != derive_audit_id(
        seed="def"
    )


def test_derive_finding_id_combines_seed_kind_ordinal() -> None:
    a = derive_finding_id(
        audit_seed="seed", kind="lineage_cycle", ordinal=0
    )
    b = derive_finding_id(
        audit_seed="seed", kind="lineage_cycle", ordinal=0
    )
    c = derive_finding_id(
        audit_seed="seed", kind="lineage_cycle", ordinal=1
    )
    d = derive_finding_id(
        audit_seed="seed", kind="lineage_gap", ordinal=0
    )
    assert a == b
    assert a != c
    assert a != d


def test_derive_boundary_id_unique_per_concern_owner() -> None:
    a = derive_boundary_id(
        concern="restrictions", owner="governance"
    )
    b = derive_boundary_id(
        concern="restrictions", owner="governance"
    )
    c = derive_boundary_id(
        concern="restrictions", owner="agents"
    )
    assert a == b
    assert a != c


def test_derive_violation_id_unique_per_offender() -> None:
    a = derive_violation_id(
        boundary_concern="approval",
        offender="agents",
        detail="x",
    )
    b = derive_violation_id(
        boundary_concern="approval",
        offender="agents",
        detail="x",
    )
    c = derive_violation_id(
        boundary_concern="approval",
        offender="supervisor",
        detail="x",
    )
    assert a == b
    assert a != c


def test_derive_helpers_reject_empty_seed() -> None:
    with pytest.raises(ValueError):
        derive_audit_id(seed="")
    with pytest.raises(ValueError):
        derive_correlation_id(seed="")
    with pytest.raises(ValueError):
        derive_trace_id(seed="")
    with pytest.raises(ValueError):
        derive_failure_record_id(seed="")
    with pytest.raises(ValueError):
        derive_dependency_audit_id(seed="")


def test_generators_emit_distinct_identifiers() -> None:
    seen = {
        generate_audit_id(),
        generate_audit_id(),
        generate_finding_id(),
        generate_trace_id(),
        generate_correlation_id(),
    }
    assert len(seen) == 5

"""Lineage-integrity validator.

Pure deterministic — given a tuple of `(node_id, parent_id_or_none)`
records, emit findings for cycles and missing parents. The
validator NEVER mutates the input.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

from app.hardening.enums import (
    HardeningFindingKind,
    HardeningSeverity,
    IntegrityStatus,
)
from app.hardening.identity import derive_finding_id
from app.hardening.models.finding import HardeningFinding


def validate_lineage(
    *,
    records: Iterable[tuple[str, str | None]],
    seed: str,
    detected_at: datetime | None = None,
) -> tuple[
    tuple[HardeningFinding, ...], IntegrityStatus
]:
    """Validate lineage records.

    Returns ``(findings, status)``. Status is PASSED iff there
    are zero findings.
    """
    if not seed:
        raise ValueError(
            "validate_lineage requires a non-empty seed"
        )
    if detected_at is None:
        detected_at = datetime.now().astimezone()
    if detected_at.tzinfo is None:
        raise ValueError(
            "validate_lineage.detected_at must be tz-aware"
        )
    parents: dict[str, str | None] = {}
    findings: list[HardeningFinding] = []
    ordinal = 0

    for node_id, parent_id in records:
        if not node_id:
            findings.append(
                HardeningFinding(
                    finding_id=derive_finding_id(
                        audit_seed=seed,
                        kind=HardeningFindingKind.LINEAGE_DRIFT.value,
                        ordinal=ordinal,
                    ),
                    ordinal=ordinal,
                    kind=HardeningFindingKind.LINEAGE_DRIFT,
                    severity=HardeningSeverity.HIGH,
                    summary="lineage record with empty node_id",
                    detected_at=detected_at,
                )
            )
            ordinal += 1
            continue
        if node_id in parents:
            findings.append(
                HardeningFinding(
                    finding_id=derive_finding_id(
                        audit_seed=seed,
                        kind=HardeningFindingKind.LINEAGE_DRIFT.value,
                        ordinal=ordinal,
                    ),
                    ordinal=ordinal,
                    kind=HardeningFindingKind.LINEAGE_DRIFT,
                    severity=HardeningSeverity.HIGH,
                    summary=(
                        f"duplicate lineage record for node "
                        f"{node_id!r}"
                    ),
                    detected_at=detected_at,
                    offender=node_id,
                )
            )
            ordinal += 1
            continue
        parents[node_id] = parent_id

    # Cycle detection (Kahn's algorithm-friendly)
    visited: set[str] = set()
    on_stack: set[str] = set()

    def _visit(node: str) -> str | None:
        if node in on_stack:
            return node  # cycle
        if node in visited:
            return None
        on_stack.add(node)
        parent = parents.get(node)
        if parent is not None:
            if parent not in parents:
                return f"missing:{parent}"
            cycle_node = _visit(parent)
            if cycle_node is not None:
                return cycle_node
        on_stack.remove(node)
        visited.add(node)
        return None

    for node in sorted(parents.keys()):
        outcome = _visit(node)
        if outcome is None:
            continue
        if outcome.startswith("missing:"):
            missing_parent = outcome.split(":", 1)[1]
            findings.append(
                HardeningFinding(
                    finding_id=derive_finding_id(
                        audit_seed=seed,
                        kind=HardeningFindingKind.LINEAGE_GAP.value,
                        ordinal=ordinal,
                    ),
                    ordinal=ordinal,
                    kind=HardeningFindingKind.LINEAGE_GAP,
                    severity=HardeningSeverity.HIGH,
                    summary=(
                        f"node {node!r} references missing "
                        f"parent {missing_parent!r}"
                    ),
                    detected_at=detected_at,
                    offender=node,
                    evidence=(missing_parent,),
                )
            )
        else:
            findings.append(
                HardeningFinding(
                    finding_id=derive_finding_id(
                        audit_seed=seed,
                        kind=HardeningFindingKind.LINEAGE_CYCLE.value,
                        ordinal=ordinal,
                    ),
                    ordinal=ordinal,
                    kind=HardeningFindingKind.LINEAGE_CYCLE,
                    severity=HardeningSeverity.CRITICAL,
                    summary=(
                        f"lineage cycle detected involving "
                        f"node {outcome!r}"
                    ),
                    detected_at=detected_at,
                    offender=outcome,
                )
            )
        ordinal += 1

    findings.sort(key=lambda f: (f.kind.value, f.ordinal))
    findings = list(_renumber(findings))
    status = (
        IntegrityStatus.PASSED
        if not findings
        else IntegrityStatus.FAILED
    )
    return tuple(findings), status


def _renumber(
    findings: list[HardeningFinding],
) -> list[HardeningFinding]:
    out: list[HardeningFinding] = []
    for ordinal, f in enumerate(findings):
        out.append(
            HardeningFinding(
                finding_id=f.finding_id,
                ordinal=ordinal,
                kind=f.kind,
                severity=f.severity,
                summary=f.summary,
                detected_at=f.detected_at,
                scope=f.scope,
                offender=f.offender,
                evidence=f.evidence,
                metadata=f.metadata,
            )
        )
    return out


class LineageIntegrityValidator:
    """Stateless object form of `validate_lineage`."""

    __slots__ = ()

    def validate(
        self,
        *,
        records: Iterable[tuple[str, str | None]],
        seed: str,
        detected_at: datetime | None = None,
    ) -> tuple[
        tuple[HardeningFinding, ...], IntegrityStatus
    ]:
        return validate_lineage(
            records=records,
            seed=seed,
            detected_at=detected_at,
        )


__all__ = [
    "LineageIntegrityValidator",
    "validate_lineage",
]

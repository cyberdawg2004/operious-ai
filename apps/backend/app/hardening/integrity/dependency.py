"""Substrate-dependency auditor.

Builds a directed dependency graph by scanning each substrate's
imports and produces a `DependencyAuditFinding`. Caller may
pass ``source_lines_by_path`` for deterministic CI tests.
"""

from __future__ import annotations

from datetime import datetime
from typing import Mapping

from app.hardening.enums import (
    HardeningSeverity,
    SubstrateName,
)
from app.hardening.identity import (
    derive_dependency_audit_id,
    derive_finding_id,
)
from app.hardening.integrity.contamination import (
    iter_source_lines,
)
from app.hardening.models.dependency import (
    DependencyAuditFinding,
    DependencyEdge,
)


_SUBSTRATE_PREFIX_MAP = {
    SubstrateName.AGENTS: ("app.agents",),
    SubstrateName.ARBITRATION: ("app.arbitration",),
    SubstrateName.BOUNDARY: ("app.boundary",),
    SubstrateName.BOUNDARY_TRANSLATION: (
        "app.boundary.translation",
    ),
    SubstrateName.BOUNDARY_VOICE: ("app.boundary.voice",),
    SubstrateName.COORDINATION: ("app.coordination",),
    SubstrateName.COORDINATION_POLICY: (
        "app.coordination.policy",
    ),
    SubstrateName.COORDINATION_TOPOLOGY: (
        "app.coordination.topology",
    ),
    SubstrateName.GOVERNANCE: ("app.governance",),
    SubstrateName.MEMORY: ("app.memory",),
    SubstrateName.ORGANIZATIONAL_INTELLIGENCE: (
        "app.organizational_intelligence",
    ),
    SubstrateName.SESSION: ("app.session",),
    SubstrateName.SUPERVISOR: (
        "app.supervisor",
        "app.supervision",
    ),
}

# Conceptual substrates have no Python import prefix because they
# represent ownership boundaries (e.g. human approval authority), not
# code substrates. They are listed here so the import-time invariant
# below can guarantee total enum coverage — adding a new
# `SubstrateName` enum value forces either a prefix mapping or an
# explicit conceptual declaration.
_CONCEPTUAL_SUBSTRATES: frozenset[SubstrateName] = frozenset(
    {SubstrateName.HUMAN}
)


def _assert_substrate_coverage() -> None:
    declared = set(_SUBSTRATE_PREFIX_MAP) | _CONCEPTUAL_SUBSTRATES
    missing = set(SubstrateName) - declared
    overlap = set(_SUBSTRATE_PREFIX_MAP) & _CONCEPTUAL_SUBSTRATES
    if missing:
        raise AssertionError(
            "Substrate-coverage invariant violated: "
            f"missing prefix mapping or conceptual declaration for "
            f"{sorted(s.value for s in missing)!r}"
        )
    if overlap:
        raise AssertionError(
            "Substrate-coverage invariant violated: "
            f"{sorted(s.value for s in overlap)!r} appear in both "
            "_SUBSTRATE_PREFIX_MAP and _CONCEPTUAL_SUBSTRATES"
        )


_assert_substrate_coverage()


def _classify_module(module: str) -> SubstrateName | None:
    candidates: list[tuple[int, SubstrateName]] = []
    for substrate, prefixes in _SUBSTRATE_PREFIX_MAP.items():
        for prefix in prefixes:
            if module == prefix or module.startswith(
                prefix + "."
            ):
                candidates.append((len(prefix), substrate))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def _import_modules(line: str) -> tuple[str, ...]:
    stripped = line.strip()
    if stripped.startswith("from "):
        rest = stripped[5:].split(" import", 1)[0].strip()
        return (rest,)
    if stripped.startswith("import "):
        rest = stripped[7:].split(" as ", 1)[0].strip()
        parts = [
            chunk.strip().split(" as ", 1)[0]
            for chunk in rest.split(",")
            if chunk.strip()
        ]
        return tuple(parts)
    return ()


def audit_dependencies(
    *,
    substrate_paths: tuple[
        tuple[SubstrateName, str], ...
    ],
    forbidden_edges: tuple[
        tuple[SubstrateName, SubstrateName], ...
    ] = (),
    seed: str,
    detected_at: datetime | None = None,
    source_lines_by_substrate: Mapping[
        SubstrateName, Mapping[str, str]
    ]
    | None = None,
) -> DependencyAuditFinding:
    if not seed:
        raise ValueError(
            "audit_dependencies requires a non-empty seed"
        )
    if detected_at is None:
        detected_at = datetime.now().astimezone()
    if detected_at.tzinfo is None:
        raise ValueError(
            "audit_dependencies.detected_at must be tz-aware"
        )

    edge_counts: dict[
        tuple[SubstrateName, SubstrateName], int
    ] = {}

    for substrate, path in substrate_paths:
        if (
            source_lines_by_substrate is not None
            and substrate in source_lines_by_substrate
        ):
            blob_iter = sorted(
                (
                    (rel_path, line_no, line)
                    for rel_path, blob in source_lines_by_substrate[
                        substrate
                    ].items()
                    for line_no, line in enumerate(
                        blob.splitlines(), start=1
                    )
                ),
                key=lambda triple: (triple[0], triple[1]),
            )
        else:
            blob_iter = iter_source_lines(path)

        for _rel_path, _line_no, line in blob_iter:
            for module in _import_modules(line):
                target = _classify_module(module)
                if target is None or target == substrate:
                    continue
                key = (substrate, target)
                edge_counts[key] = edge_counts.get(key, 0) + 1

    edges_sorted = sorted(
        edge_counts.items(),
        key=lambda kv: (
            kv[0][0].value,
            kv[0][1].value,
        ),
    )
    edges = tuple(
        DependencyEdge(
            source=source, target=target, occurrences=count
        )
        for (source, target), count in edges_sorted
    )

    forbidden_lookup = {
        (s, t) for (s, t) in forbidden_edges
    }
    forbidden_observed = tuple(
        edge
        for edge in edges
        if (edge.source, edge.target) in forbidden_lookup
    )

    severity = (
        HardeningSeverity.CRITICAL
        if forbidden_observed
        else HardeningSeverity.INFO
    )
    summary = (
        f"observed {len(edges)} cross-substrate edges; "
        f"{len(forbidden_observed)} forbidden"
    )

    audit_id = derive_dependency_audit_id(seed=seed)
    finding_id = derive_finding_id(
        audit_seed=seed,
        kind="dependency_audit",
        ordinal=0,
    )

    return DependencyAuditFinding(
        finding_id=finding_id,
        audit_id=audit_id,
        edges=edges,
        forbidden_edges=forbidden_observed,
        severity=severity,
        summary=summary,
        detected_at=detected_at,
    )


class DependencyAuditor:
    __slots__ = ()

    def audit(
        self,
        *,
        substrate_paths: tuple[
            tuple[SubstrateName, str], ...
        ],
        forbidden_edges: tuple[
            tuple[SubstrateName, SubstrateName], ...
        ] = (),
        seed: str,
        detected_at: datetime | None = None,
        source_lines_by_substrate: Mapping[
            SubstrateName, Mapping[str, str]
        ]
        | None = None,
    ) -> DependencyAuditFinding:
        return audit_dependencies(
            substrate_paths=substrate_paths,
            forbidden_edges=forbidden_edges,
            seed=seed,
            detected_at=detected_at,
            source_lines_by_substrate=source_lines_by_substrate,
        )


__all__ = ["DependencyAuditor", "audit_dependencies"]

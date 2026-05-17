"""Contamination detector — scans a substrate's source for forbidden imports.

The detector is **read-only**. It performs simple textual
analysis without executing or importing anything from the
target substrate.

For tests, callers can also pass ``source_lines_by_path`` to
inject a fake source-snapshot, which preserves determinism in
CI without depending on filesystem state.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Iterable, Mapping

from app.hardening.enums import (
    HardeningFindingKind,
    HardeningSeverity,
    IntegrityStatus,
    SubstrateName,
)
from app.hardening.identity import derive_finding_id
from app.hardening.models.finding import HardeningFinding


_PY_EXT = ".py"


def _iter_source_lines(
    substrate_path: str,
) -> Iterable[tuple[str, int, str]]:
    """Walk substrate_path and yield (rel_path, line_no, line)."""
    if not os.path.isdir(substrate_path):
        return
    for dirpath, dirnames, filenames in os.walk(
        substrate_path
    ):
        dirnames.sort()
        if "__pycache__" in dirnames:
            dirnames.remove("__pycache__")
        for filename in sorted(filenames):
            if not filename.endswith(_PY_EXT):
                continue
            file_path = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(
                file_path, substrate_path
            )
            try:
                with open(
                    file_path, "r", encoding="utf-8"
                ) as fp:
                    for line_no, line in enumerate(
                        fp.readlines(), start=1
                    ):
                        yield rel_path, line_no, line
            except OSError:
                continue


def detect_contamination(
    *,
    substrate: SubstrateName,
    substrate_path: str,
    forbidden_module_prefixes: tuple[str, ...],
    seed: str,
    detected_at: datetime | None = None,
    source_lines_by_path: Mapping[str, str] | None = None,
) -> tuple[
    tuple[HardeningFinding, ...], IntegrityStatus
]:
    """Detect forbidden cross-substrate imports.

    Args:
        substrate:                The substrate being audited.
        substrate_path:           Filesystem path to the package.
        forbidden_module_prefixes: e.g. ``("app.governance",)``.
        seed:                     Deterministic finding seed.
        detected_at:              Optional timestamp.
        source_lines_by_path:     Optional override for tests.
    """
    if not seed:
        raise ValueError(
            "detect_contamination requires a non-empty seed"
        )
    if detected_at is None:
        detected_at = datetime.now().astimezone()
    if detected_at.tzinfo is None:
        raise ValueError(
            "detect_contamination.detected_at must be tz-aware"
        )
    findings: list[HardeningFinding] = []
    ordinal = 0

    if source_lines_by_path is not None:
        iterator: Iterable[tuple[str, int, str]] = sorted(
            (
                (path, line_no, line)
                for path, blob in source_lines_by_path.items()
                for line_no, line in enumerate(
                    blob.splitlines(), start=1
                )
            ),
            key=lambda triple: (triple[0], triple[1]),
        )
    else:
        iterator = _iter_source_lines(substrate_path)

    for rel_path, line_no, line in iterator:
        stripped = line.strip()
        if not (
            stripped.startswith("import ")
            or stripped.startswith("from ")
        ):
            continue
        for prefix in forbidden_module_prefixes:
            if (
                stripped.startswith(f"from {prefix}")
                or stripped.startswith(f"import {prefix}")
            ):
                findings.append(
                    HardeningFinding(
                        finding_id=derive_finding_id(
                            audit_seed=seed,
                            kind=HardeningFindingKind.CONTAMINATION_IMPORT.value,
                            ordinal=ordinal,
                        ),
                        ordinal=ordinal,
                        kind=HardeningFindingKind.CONTAMINATION_IMPORT,
                        severity=HardeningSeverity.CRITICAL,
                        summary=(
                            f"{substrate.value} imports forbidden "
                            f"module prefix {prefix!r}"
                        ),
                        detected_at=detected_at,
                        scope=substrate.value,
                        offender=f"{rel_path}:{line_no}",
                        evidence=(stripped,),
                    )
                )
                ordinal += 1
                break

    status = (
        IntegrityStatus.PASSED
        if not findings
        else IntegrityStatus.FAILED
    )
    return tuple(findings), status


class ContaminationDetector:
    __slots__ = ()

    def detect(
        self,
        *,
        substrate: SubstrateName,
        substrate_path: str,
        forbidden_module_prefixes: tuple[str, ...],
        seed: str,
        detected_at: datetime | None = None,
        source_lines_by_path: Mapping[str, str] | None = None,
    ) -> tuple[
        tuple[HardeningFinding, ...], IntegrityStatus
    ]:
        return detect_contamination(
            substrate=substrate,
            substrate_path=substrate_path,
            forbidden_module_prefixes=forbidden_module_prefixes,
            seed=seed,
            detected_at=detected_at,
            source_lines_by_path=source_lines_by_path,
        )


__all__ = [
    "ContaminationDetector",
    "detect_contamination",
]

"""Deterministic SOP analyzer.

The analyzer is **purely lexical** — it inspects the canonical SOP
body for known ambiguity / contradiction / escalation-gap markers
and emits findings deterministically. It does NOT call any LLM,
does NOT fetch external data, and does NOT modify the SOP.

The marker catalogues live as module-level frozensets so they are
inspectable and pinnable in tests.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.organizational_intelligence.enums import (
    SopFindingKind,
    SopFindingSeverity,
)
from app.organizational_intelligence.identity import (
    derive_sop_finding_id,
)
from app.organizational_intelligence.models.sop import (
    SopFinding,
    SopVersion,
)


_AMBIGUITY_MARKERS: frozenset[str] = frozenset(
    {
        "maybe",
        "perhaps",
        "as appropriate",
        "as needed",
        "if reasonable",
        "tbd",
        "unclear",
        "tentative",
    }
)
_CONTRADICTION_MARKERS: frozenset[str] = frozenset(
    {
        "always but never",
        "must and must not",
        "required and forbidden",
    }
)
_ESCALATION_GAP_MARKERS: frozenset[str] = frozenset(
    {
        "no escalation",
        "do not escalate",
        "escalation not defined",
    }
)
_MISSING_AUTHORITY_MARKERS: frozenset[str] = frozenset(
    {
        "approver tbd",
        "owner unknown",
        "manager pending",
    }
)
_OUTDATED_MARKERS: frozenset[str] = frozenset(
    {
        "deprecated",
        "obsolete",
        "no longer used",
    }
)


_ANALYZER_SIGNATURE = "deterministic.sop.v1"


class DeterministicSopAnalyzer:
    """Pure deterministic SOP analyzer.

    Stateless. Two callers running the same body produce the same
    findings byte-identically.
    """

    __slots__ = ()

    @property
    def signature(self) -> str:
        return _ANALYZER_SIGNATURE

    def analyze(
        self, *, sop_version: SopVersion
    ) -> tuple[SopFinding, ...]:
        body_lower = sop_version.body.lower()
        findings: list[SopFinding] = []
        ordinal = 0
        detected_at = datetime.now(tz=timezone.utc)

        ordinal = self._scan(
            body_lower=body_lower,
            markers=_AMBIGUITY_MARKERS,
            kind=SopFindingKind.AMBIGUITY,
            severity=SopFindingSeverity.MEDIUM,
            sop_version=sop_version,
            findings=findings,
            ordinal=ordinal,
            detected_at=detected_at,
        )
        ordinal = self._scan(
            body_lower=body_lower,
            markers=_CONTRADICTION_MARKERS,
            kind=SopFindingKind.CONTRADICTION,
            severity=SopFindingSeverity.HIGH,
            sop_version=sop_version,
            findings=findings,
            ordinal=ordinal,
            detected_at=detected_at,
        )
        ordinal = self._scan(
            body_lower=body_lower,
            markers=_ESCALATION_GAP_MARKERS,
            kind=SopFindingKind.ESCALATION_GAP,
            severity=SopFindingSeverity.HIGH,
            sop_version=sop_version,
            findings=findings,
            ordinal=ordinal,
            detected_at=detected_at,
        )
        ordinal = self._scan(
            body_lower=body_lower,
            markers=_MISSING_AUTHORITY_MARKERS,
            kind=SopFindingKind.MISSING_AUTHORITY,
            severity=SopFindingSeverity.HIGH,
            sop_version=sop_version,
            findings=findings,
            ordinal=ordinal,
            detected_at=detected_at,
        )
        ordinal = self._scan(
            body_lower=body_lower,
            markers=_OUTDATED_MARKERS,
            kind=SopFindingKind.OUTDATED_REFERENCE,
            severity=SopFindingSeverity.LOW,
            sop_version=sop_version,
            findings=findings,
            ordinal=ordinal,
            detected_at=detected_at,
        )

        findings.sort(
            key=lambda f: (f.kind.value, f.ordinal)
        )
        return tuple(findings)

    @staticmethod
    def _scan(
        *,
        body_lower: str,
        markers: frozenset[str],
        kind: SopFindingKind,
        severity: SopFindingSeverity,
        sop_version: SopVersion,
        findings: list[SopFinding],
        ordinal: int,
        detected_at: datetime,
    ) -> int:
        for marker in sorted(markers):
            if marker in body_lower:
                findings.append(
                    SopFinding(
                        finding_id=derive_sop_finding_id(
                            sop_id=sop_version.sop_id,
                            version=sop_version.version,
                            ordinal=ordinal,
                        ),
                        sop_id=sop_version.sop_id,
                        sop_version=sop_version.version,
                        ordinal=ordinal,
                        kind=kind,
                        severity=severity,
                        summary=(
                            f"Detected {kind.value} marker: "
                            f"{marker!r}"
                        ),
                        location_hint=marker,
                        evidence=(marker,),
                        detected_at=detected_at,
                    )
                )
                ordinal += 1
        return ordinal


__all__ = ["DeterministicSopAnalyzer"]

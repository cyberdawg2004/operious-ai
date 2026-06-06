"""Semantic preservation checks for model-produced diagnostic output."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.cognition.exceptions import CognitionSemanticValidationError

_GOVERNANCE_TERMS: frozenset[str] = frozenset(
    {
        "approve",
        "approved",
        "chargeback",
        "compliance",
        "credit",
        "deny",
        "denied",
        "escalate",
        "fraud",
        "legal",
        "refund",
        "reject",
        "rejected",
        "replacement",
        "rma",
    }
)
_TOKEN_RE = re.compile(r"[a-z0-9_]+")


@dataclass(frozen=True, slots=True)
class SemanticPreservationResult:
    canonical_terms: tuple[str, ...]
    output_terms: tuple[str, ...]
    missing_terms: tuple[str, ...]
    introduced_terms: tuple[str, ...]
    allowed_terms: tuple[str, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.missing_terms and not self.introduced_terms


def validate_governance_terms(
    *,
    canonical_text: str,
    output_text: str,
    allowed_text: str | None = None,
) -> SemanticPreservationResult:
    """Ensure model output does not drop or invent governance terms."""

    result = inspect_governance_terms(
        canonical_text=canonical_text,
        output_text=output_text,
        allowed_text=allowed_text,
    )
    if not result.valid:
        raise CognitionSemanticValidationError(
            "model output drifted governance-significant terms"
        )
    return result


def inspect_governance_terms(
    *,
    canonical_text: str,
    output_text: str,
    allowed_text: str | None = None,
) -> SemanticPreservationResult:
    """Return governance-term drift detail without raising."""

    canonical_terms = _terms(canonical_text)
    allowed_terms = (
        canonical_terms if allowed_text is None else _terms(allowed_text)
    )
    output_terms = _terms(output_text)
    return SemanticPreservationResult(
        canonical_terms=tuple(sorted(canonical_terms)),
        allowed_terms=tuple(sorted(allowed_terms)),
        output_terms=tuple(sorted(output_terms)),
        missing_terms=tuple(sorted(canonical_terms - output_terms)),
        introduced_terms=tuple(sorted(output_terms - allowed_terms)),
    )


def _terms(text: str) -> set[str]:
    tokens = set(_TOKEN_RE.findall(text.casefold()))
    return tokens & _GOVERNANCE_TERMS


__all__ = [
    "SemanticPreservationResult",
    "inspect_governance_terms",
    "validate_governance_terms",
]

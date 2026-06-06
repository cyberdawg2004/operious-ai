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

# Standard remediation vocabulary the diagnostic agent is authorized to name
# even when a cited SOP does not spell it out verbatim. Higher-stakes terms
# (approve/deny/fraud/legal/chargeback/compliance/reject) are deliberately
# excluded — they remain grounding-gated.
DEFAULT_AUTHORIZED_GOVERNANCE_TERMS: frozenset[str] = frozenset(
    {"refund", "replacement", "credit", "rma", "escalate"}
)


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
    authorized_terms: frozenset[str] = frozenset(),
) -> SemanticPreservationResult:
    """Ensure model output does not drop or invent governance terms."""

    result = inspect_governance_terms(
        canonical_text=canonical_text,
        output_text=output_text,
        allowed_text=allowed_text,
        authorized_terms=authorized_terms,
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
    authorized_terms: frozenset[str] = frozenset(),
) -> SemanticPreservationResult:
    """Return governance-term drift detail without raising.

    ``authorized_terms`` is the tenant's explicitly authorized remediation
    vocabulary (e.g. ``refund``, ``replacement``, ``credit``, ``rma``,
    ``escalate``). Those may appear in the output even when not literally
    grounded — the agent is permitted to name authorized remediations. Terms
    that are neither grounded NOR authorized (e.g. ``fraud``, ``legal``,
    ``chargeback``) still fail closed. ``missing`` drift (dropping a term the
    customer used) is unaffected by the allowlist.
    """

    canonical_terms = _terms(canonical_text)
    allowed_terms = (
        canonical_terms if allowed_text is None else _terms(allowed_text)
    )
    # Authorized remediation vocabulary is permitted even when ungrounded.
    allowed_terms = allowed_terms | (authorized_terms & _GOVERNANCE_TERMS)
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
    "DEFAULT_AUTHORIZED_GOVERNANCE_TERMS",
    "SemanticPreservationResult",
    "inspect_governance_terms",
    "validate_governance_terms",
]

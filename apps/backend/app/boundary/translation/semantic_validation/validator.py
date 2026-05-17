"""`SemanticPreservationValidator` — pure governance-keyword check.

The validator is deterministic and observational. It compares
two payloads and emits a `SemanticPreservationCheck` reporting:

* governance tokens present in canonical but missing in boundary
  (or vice-versa for ingress),
* governance tokens injected ONLY in boundary that were not in
  canonical.

The validator NEVER edits text. Its only role is to surface
authority drift. It does NOT classify operational meaning — it
only checks for known reserved-word integrity.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

from app.boundary.translation.enums import (
    SemanticPreservationStatus,
)
from app.boundary.translation.models.preservation import (
    SemanticPreservationCheck,
)


# ─── Pinned governance / escalation token catalogue ─────────────────


GOVERNANCE_KEYWORDS: frozenset[str] = frozenset(
    {
        "approve",
        "approved",
        "authorize",
        "authorized",
        "block",
        "blocked",
        "compliance",
        "deny",
        "denied",
        "escalate",
        "escalated",
        "escalation",
        "forbidden",
        "governance",
        "policy",
        "prohibited",
        "restricted",
        "restriction",
        "sanction",
        "sla",
        "violation",
    }
)


def _tokenise(text: str) -> set[str]:
    """Lowercase tokenisation on word characters only.

    The implementation is intentionally trivial. Multilingual
    matching is the responsibility of a translation provider's
    semantic-preservation contract; the validator here only
    asserts that **canonical-English** governance keywords are
    not silently lost or injected.
    """
    out: set[str] = set()
    buf: list[str] = []
    for ch in text:
        if ch.isalnum() or ch == "_":
            buf.append(ch.lower())
        else:
            if buf:
                out.add("".join(buf))
                buf = []
    if buf:
        out.add("".join(buf))
    return out


def check_semantic_preservation(
    *,
    canonical_text: str,
    candidate_text: str,
    detected_at: datetime | None = None,
    keywords: Iterable[str] | None = None,
) -> SemanticPreservationCheck:
    """Pure semantic-preservation check.

    Args:
        canonical_text:    The canonical-English text.
        candidate_text:    The translated text to compare.
        detected_at:       Optional UTC timestamp.
        keywords:          Optional override for the keyword
                            catalogue.
    """
    if detected_at is None:
        detected_at = datetime.now().astimezone()
    if detected_at.tzinfo is None:
        raise ValueError(
            "check_semantic_preservation.detected_at must be tz-aware"
        )
    catalogue = (
        frozenset(keywords)
        if keywords is not None
        else GOVERNANCE_KEYWORDS
    )

    canonical_tokens = _tokenise(canonical_text)
    candidate_tokens = _tokenise(candidate_text)

    canonical_governance = canonical_tokens & catalogue
    candidate_governance = candidate_tokens & catalogue

    missing = canonical_governance - candidate_governance
    introduced = candidate_governance - canonical_governance

    if not missing and not introduced:
        status = SemanticPreservationStatus.PRESERVED
        summary = "governance tokens preserved"
    elif missing and not introduced:
        status = SemanticPreservationStatus.DRIFTED
        summary = (
            f"governance tokens missing from translation: "
            f"{sorted(missing)}"
        )
    elif introduced and not missing:
        status = SemanticPreservationStatus.SUSPICIOUS
        summary = (
            f"governance tokens introduced by translation: "
            f"{sorted(introduced)}"
        )
    else:
        status = SemanticPreservationStatus.DRIFTED
        summary = (
            f"governance tokens drifted: "
            f"missing={sorted(missing)} "
            f"introduced={sorted(introduced)}"
        )

    return SemanticPreservationCheck(
        status=status,
        summary=summary,
        detected_at=detected_at,
        canonical_tokens_present=tuple(
            sorted(canonical_governance)
        ),
        canonical_tokens_missing=tuple(sorted(missing)),
        introduced_governance_tokens=tuple(
            sorted(introduced)
        ),
    )


class SemanticPreservationValidator:
    """Stateless object form of `check_semantic_preservation`."""

    __slots__ = ("_keywords",)

    def __init__(
        self,
        keywords: Iterable[str] | None = None,
    ) -> None:
        self._keywords = (
            frozenset(keywords)
            if keywords is not None
            else GOVERNANCE_KEYWORDS
        )

    @property
    def keywords(self) -> frozenset[str]:
        return self._keywords

    def validate(
        self,
        *,
        canonical_text: str,
        candidate_text: str,
        detected_at: datetime | None = None,
    ) -> SemanticPreservationCheck:
        return check_semantic_preservation(
            canonical_text=canonical_text,
            candidate_text=candidate_text,
            detected_at=detected_at,
            keywords=self._keywords,
        )


__all__ = [
    "GOVERNANCE_KEYWORDS",
    "SemanticPreservationValidator",
    "check_semantic_preservation",
]

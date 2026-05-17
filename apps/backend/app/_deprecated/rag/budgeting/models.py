"""Budgeting data shapes.

Three types:

* `BudgetConstraint` — the immutable inputs.
* `BudgetingDecision` — one per candidate; explicit include/exclude
  outcome plus the *reason* and the *token cost* the estimator
  attributed.
* `BudgetingResult` — the populated outcome the assembly pipeline
  consumes.

Every type is frozen and slotted. Reasons are an explicit string-enum
so audit / governance can filter exclusions without parsing free text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping

from app._deprecated.rag.retrieval.models import RetrievalCandidate


class BudgetingDecisionReason(StrEnum):
    """Explicit reasons a candidate was excluded.

    Included candidates carry `INCLUDED`. Every other value is an
    exclusion — kept explicit so dashboards can attribute drops.
    """

    INCLUDED = "included"
    EXCEEDED_TOKEN_BUDGET = "exceeded_token_budget"
    EXCEEDED_CHUNK_BUDGET = "exceeded_chunk_budget"
    EXCEEDED_PER_DOCUMENT_CAP = "exceeded_per_document_cap"
    BELOW_MIN_SCORE = "below_min_score"


@dataclass(frozen=True, slots=True)
class BudgetConstraint:
    """The constraint set applied during packing.

    Attributes:
        max_tokens:           Hard ceiling on the sum of estimated
                              token cost across included candidates.
                              `None` disables.
        max_chunks:           Hard ceiling on the number of included
                              candidates. `None` disables.
        max_chunks_per_doc:   Per-document chunk cap. `None` disables.
        min_score:            Per-candidate score floor applied during
                              packing (independent of the policy floor;
                              budgeting can tighten further).
        estimator_name:       Name of the estimator used. Recorded for
                              audit; the actual estimator is passed
                              into `apply_budget`.
    """

    max_tokens: int | None = None
    max_chunks: int | None = None
    max_chunks_per_doc: int | None = None
    min_score: float | None = None
    estimator_name: str = ""

    def __post_init__(self) -> None:
        for name, value in (
            ("max_tokens", self.max_tokens),
            ("max_chunks", self.max_chunks),
            ("max_chunks_per_doc", self.max_chunks_per_doc),
        ):
            if value is not None and value < 0:
                raise ValueError(f"{name} must be >= 0, got {value}")


@dataclass(frozen=True, slots=True)
class BudgetingDecision:
    """Per-candidate budgeting outcome."""

    candidate: RetrievalCandidate
    reason: BudgetingDecisionReason
    estimated_tokens: int

    @property
    def included(self) -> bool:
        return self.reason is BudgetingDecisionReason.INCLUDED


@dataclass(frozen=True, slots=True)
class BudgetingResult:
    """Populated budgeting outcome consumed by the assembly pipeline.

    Attributes:
        constraint:        The constraint applied.
        decisions:         One decision per input candidate, preserving
                           the input order. Audit-grade traceability.
        included:          Convenience tuple of `RetrievalCandidate`s
                           where `decision.included` is True. Same order
                           as `decisions`.
        excluded:          Convenience tuple of `RetrievalCandidate`s
                           where `decision.included` is False.
        total_tokens:      Sum of estimated tokens across included.
        included_count:    `len(included)`.
        excluded_count:    `len(excluded)`.
        metadata:          Opaque.
    """

    constraint: BudgetConstraint
    decisions: tuple[BudgetingDecision, ...]
    included: tuple[RetrievalCandidate, ...]
    excluded: tuple[RetrievalCandidate, ...]
    total_tokens: int
    included_count: int
    excluded_count: int
    metadata: Mapping[str, Any] = field(default_factory=dict)


__all__ = [
    "BudgetingDecisionReason",
    "BudgetConstraint",
    "BudgetingDecision",
    "BudgetingResult",
]

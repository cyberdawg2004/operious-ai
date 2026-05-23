"""Context budgeting runtime.

Given a (reranked) candidate set and a `BudgetConstraint`, the budgeting
subsystem produces a `BudgetingResult` that declares — explicitly,
inspectably, deterministically — which candidates make it into the
assembled context and which are cut, and why.

Determinism contract:

* the input candidate order is treated as authoritative — packing is
  greedy in that order,
* on ties (e.g., two candidates equally expensive at the budget edge)
  the candidate appearing earlier in the input wins,
* token estimation is performed by a pluggable `BaseTokenEstimator`;
  the only estimator shipping in Sprint H is `HeuristicTokenEstimator`,
  which is `len(text) // ratio` — a pure function. Tokenizer-backed
  estimators (cl100k_base, etc.) can be added later without changing
  the budgeting algorithm.

Architectural rules:

* budgeting is pure: it reads candidates, returns a result, does no I/O,
* per-document caps (`max_chunks_per_doc`) are enforced in input order,
* dropped candidates carry an explicit `BudgetingDecisionReason`.
"""

from app.rag.budgeting.estimator import (
    BaseTokenEstimator,
    HeuristicTokenEstimator,
)
from app.rag.budgeting.models import (
    BudgetConstraint,
    BudgetingDecision,
    BudgetingDecisionReason,
    BudgetingResult,
)
from app.rag.budgeting.service import apply_budget

__all__ = [
    "BaseTokenEstimator",
    "HeuristicTokenEstimator",
    "BudgetConstraint",
    "BudgetingDecision",
    "BudgetingDecisionReason",
    "BudgetingResult",
    "apply_budget",
]

"""Grounding runtime foundations.

A `GroundingFragment` is one citation-tagged unit of evidence the
context exposes to downstream consumers (future agent runtimes, AI
gateway prompts, governance pipelines). The `GroundingResult` is the
ordered set of fragments produced for one assembly call.

Sprint H ships ONE grounding strategy (`DefaultGroundingStrategy`) that
emits one fragment per included candidate. Future strategies might
deduplicate by document, summarise, or reweave overlapping chunks — all
behind the same `BaseGroundingStrategy` contract.

Architectural rules:

* grounding is a **pure** transform — no I/O, no provider calls,
* grounding consumes (candidates, citation index) and produces fragments,
* grounding NEVER mutates the candidates, citations, or budgeting result,
* grounding NEVER builds prompts. Prompt construction is a future
  sprint, not Sprint H.
"""

from app.rag.grounding.base import BaseGroundingStrategy
from app.rag.grounding.default import DefaultGroundingStrategy
from app.rag.grounding.models import GroundingFragment, GroundingResult

__all__ = [
    "BaseGroundingStrategy",
    "DefaultGroundingStrategy",
    "GroundingFragment",
    "GroundingResult",
]

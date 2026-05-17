"""Reranking substrate foundations.

Sprint H ships ONLY the contract and an identity reranker. No ML
rerankers, no external providers, no hidden ranking logic — those are
explicitly deferred.

The point of this sub-package is to establish:

* the **interface** (`BaseReranker`) every future reranker must honour,
* the **envelope** shape (`RerankingEnvelope`) — never raises,
* a working pass-through (`IdentityReranker`) so the assembly pipeline
  has a deterministic default,
* a **registry** so future rerankers can be selected by name without
  changing call sites.

Architectural rules:

* a reranker MAY reorder, MAY drop, MAY annotate metadata, but MUST NOT
  invent candidates,
* a reranker MUST be deterministic given fixed input,
* a reranker MUST be replayable — no wall-clock seeds, no global RNG.
"""

from app._deprecated.rag.reranking.base import BaseReranker
from app._deprecated.rag.reranking.envelopes import RerankingEnvelope
from app._deprecated.rag.reranking.identity import IdentityReranker
from app._deprecated.rag.reranking.models import RerankingRequest, RerankingResult
from app._deprecated.rag.reranking.registry import RerankerRegistry
from app._deprecated.rag.reranking.tracing import RerankingTrace

__all__ = [
    "BaseReranker",
    "RerankingEnvelope",
    "IdentityReranker",
    "RerankingRequest",
    "RerankingResult",
    "RerankerRegistry",
    "RerankingTrace",
]

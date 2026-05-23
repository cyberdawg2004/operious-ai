"""Retrieval orchestration runtime.

The layer ABOVE `app.memory.retrieval`. The Sprint G retrieval service
runs ONE embedding + ONE vector query; this sub-package introduces:

* a **strategy** abstraction (`BaseRetrievalStrategy`) so different
  retrieval shapes (single-query today, hybrid / multi-source later)
  share the same contract,
* a **runtime** (`RetrievalRuntime`) that:
    - dispatches one or more named strategies,
    - normalises every strategy's output into a single, deterministic
      `RetrievalCandidateSet`,
    - applies the active `RetrievalPolicy`,
    - emits one envelope, never raising.

The runtime is intentionally synchronous in strategy execution today.
Concurrent fan-out is a future-sprint concern and lands here, not at
call sites.

Architectural rules:
* strategies consume `RetrievalService` (or future read-side services);
  they MUST NOT touch the vector provider or embedding gateway directly,
* the runtime is the ONLY producer of `RetrievalCandidateSet`,
* every envelope returned by this package is frozen.
"""

from app.rag.retrieval.base import BaseRetrievalStrategy
from app.rag.retrieval.envelopes import RetrievalRuntimeEnvelope
from app.rag.retrieval.models import (
    RetrievalCandidate,
    RetrievalCandidateSet,
    RetrievalRuntimeRequest,
    RetrievalStrategyInfo,
)
from app.rag.retrieval.runtime import RetrievalRuntime
from app.rag.retrieval.single_query import SingleQueryStrategy
from app.rag.retrieval.tracing import RetrievalRuntimeTrace, StrategyInvocationTrace

__all__ = [
    "BaseRetrievalStrategy",
    "RetrievalRuntimeEnvelope",
    "RetrievalCandidate",
    "RetrievalCandidateSet",
    "RetrievalRuntimeRequest",
    "RetrievalStrategyInfo",
    "RetrievalRuntime",
    "SingleQueryStrategy",
    "RetrievalRuntimeTrace",
    "StrategyInvocationTrace",
]

"""Retrieval policy infrastructure.

A `RetrievalPolicy` is the **explicit** configuration a retrieval runtime
honours for a single request: top-k, minimum score, allowed sources,
metadata filter, tenant scope. Policies are frozen dataclasses, hashable
and replayable. They are the *only* legitimate place to express
"how should retrieval behave for this caller?"

What lives here:

* `models`       — `RetrievalPolicy` (the frozen contract).
* `enforcement`  — pure-function predicates the retrieval runtime + the
                   budgeting pipeline call on candidates.

What MUST NOT live here:

* I/O. The policy module is pure.
* Provider-specific filter DSLs. The policy speaks the platform's
  vendor-neutral vocabulary; providers translate it.
* Authorization / authn. Policies *carry* tenant scope; they do not
  authenticate it. Authentication is a transport-layer concern in a
  later sprint.
"""

from app.rag.policies.enforcement import (
    candidate_matches_policy,
    filter_candidates_by_policy,
)
from app.rag.policies.models import RetrievalPolicy

__all__ = [
    "RetrievalPolicy",
    "candidate_matches_policy",
    "filter_candidates_by_policy",
]

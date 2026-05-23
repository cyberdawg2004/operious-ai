"""Governance guardrails.

The guardrail layer is the **integration boundary** between the
governance substrate (`app/governance/*`) and the operational
runtimes (Sprint G / H). It is the ONLY place governance reaches into
non-governance code.

Two things live here:

* `BaseGuardrail` — the abstract per-stage seam. A guardrail observes
  one or more enforcement stages and converts a `GovernanceDecision`
  into actual operational effect on a target runtime.

* `GovernedAssemblyRuntime` — the shipping composition wrapper for
  Sprint I. Wraps `GovernanceRuntime` + `ContextAssemblyService`,
  runs governance at PRE_RETRIEVAL and PRE_EXECUTION, and returns a
  combined envelope where governance + context envelopes sit
  side-by-side (same composition pattern Sprint H uses for retrieval
  + reranking sub-envelopes inside `ContextEnvelope`).

What does NOT live here:

* policies — they live under `app/governance/policies/`,
* enforcement handlers — they live under `app/governance/enforcement/`.

The guardrail layer assumes the substrate is configured; its only job
is to wire it into operational pipelines.

Why we ship one composition wrapper (not modifications to Sprint H):

Sprint H contracts (`AssemblyRequest`, `AssembledContext`,
`RetrievalCandidateSet`) are authoritative. Composing here keeps
Sprint G/H code paths untouched, preserves every Sprint H test, and
lets a future integration sprint add fine-grained hooks (POST_RETRIEVAL,
PRE_GROUNDING) without disturbing the substrate.
"""

from app.governance.guardrails.adapters import (
    GovernedAssembledContext,
    GovernedAssemblyEnvelope,
    GovernedAssemblyRequest,
    GovernedAssemblyRuntime,
)

__all__ = [
    "GovernedAssembledContext",
    "GovernedAssemblyEnvelope",
    "GovernedAssemblyRequest",
    "GovernedAssemblyRuntime",
]

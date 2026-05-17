"""Retrieval-augmented generation runtime substrate (Sprint H).

`app/rag/` is the **operational layer** that sits ABOVE the Sprint G
retrieval primitives. It does not own retrieval; it orchestrates
retrieval into deterministic, replayable, citation-aware *context* that
downstream consumers (AI gateway, future agent runtimes, governance
pipelines) can ground their decisions on.

Sub-packages — each with one narrow responsibility:

* `policies/`    — retrieval policy contracts + enforcement (pure).
* `retrieval/`   — strategy contract + retrieval runtime (sequencing /
                   normalisation / candidate merging).
* `reranking/`   — substrate interfaces and the identity reranker.
                   No ML rerankers ship in Sprint H by design.
* `budgeting/`   — token + chunk budgeting, deterministic packing.
* `citations/`   — citation lineage models + pure-function builder.
* `grounding/`   — grounding fragment models + default strategy.
* `assembly/`    — `ContextAssemblyService`, the apex orchestrator.

What lives here:
* Explicit runtime classes (services, runtimes, strategies).
* Frozen Pydantic-less dataclasses (every Sprint H type is immutable).
* Pure-function transforms (citations, budgeting, grounding).
* Envelopes that never raise.

What does NOT live here (architectural invariants):
* Prompt rendering / prompt templates.
* Vendor SDK imports (only `app/providers/*_provider.py` may).
* Direct vector-provider coupling — the retrieval runtime composes
  `app.memory.retrieval.RetrievalService`; it does not reach into the
  vector provider.
* Autonomous loops, recursive orchestration, agent runtimes.
* Memory mutation logic — RAG is read-only with respect to operational
  memory.

The package is intentionally readable top-to-bottom: open
`app/rag/assembly/service.py` and you will see the entire context
assembly pipeline in one method.
"""

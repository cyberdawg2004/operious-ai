"""Context assembly runtime.

`ContextAssemblyService` is the apex orchestrator of Sprint H. One
public method (`assemble`) runs the pipeline:

    request → retrieval runtime → reranker → budgeting → citations → grounding → envelope

Determinism, replayability, and inspectability are *composition
properties* — every stage is independently deterministic, so the whole
pipeline is too. The trace shape lets a replayer reconstruct lineage
without re-running anything.
"""

from app.rag.assembly.envelopes import ContextEnvelope
from app.rag.assembly.models import AssembledContext, AssemblyRequest
from app.rag.assembly.service import ContextAssemblyService
from app.rag.assembly.tracing import AssemblyTrace

__all__ = [
    "ContextEnvelope",
    "AssembledContext",
    "AssemblyRequest",
    "ContextAssemblyService",
    "AssemblyTrace",
]

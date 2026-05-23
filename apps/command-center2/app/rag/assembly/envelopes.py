"""Context envelope.

Never-raising container around an assembly outcome. Carries:

* the assembly trace (always),
* the assembled context (on success),
* the retrieval-runtime envelope (always — failure or success, so
  replayers can read the retrieval sub-trace even when the assembly
  failed mid-pipeline),
* the reranking envelope (when the pipeline reached the reranking
  stage),
* the underlying error (on failure).

The envelope is the **one** artefact downstream consumers / orchestration
tasks / replay tooling read.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.rag.assembly.models import AssembledContext
from app.rag.assembly.tracing import AssemblyTrace
from app.rag.reranking.envelopes import RerankingEnvelope
from app.rag.retrieval.envelopes import RetrievalRuntimeEnvelope


@dataclass(frozen=True, slots=True)
class ContextEnvelope:
    """Never-raising container around a context-assembly outcome."""

    trace: AssemblyTrace
    result: AssembledContext | None = None
    error: BaseException | None = None

    # Sub-envelopes preserved for replay / governance.
    retrieval_envelope: RetrievalRuntimeEnvelope | None = None
    reranking_envelope: RerankingEnvelope | None = None

    @property
    def is_ok(self) -> bool:
        return self.error is None and self.result is not None

    def unwrap(self) -> AssembledContext:
        if not self.is_ok:
            raise RuntimeError(
                "ContextEnvelope.unwrap() called on a failed envelope; "
                "inspect .trace, .error, .retrieval_envelope first."
            ) from self.error
        assert self.result is not None
        return self.result


__all__ = ["ContextEnvelope"]

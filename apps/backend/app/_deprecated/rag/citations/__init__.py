"""Citation lineage runtime.

A `Citation` is a stable, 1-based reference back to the chunk that
contributed a piece of grounding. The `CitationIndex` is the
authoritative mapping `index → Citation` for one assembled context.

The builder is a pure function: candidates in → citation index out.
Same input → byte-identical output, including stable citation numbering.

Architectural rules:

* citation indices are 1-based — they exist for human-readable
  reference in downstream UIs / prompts (NOT built here); 0 is
  intentionally avoided,
* citation numbering reflects the **post-budget** order of the candidate
  set; the assembly service guarantees the input is already in that
  order,
* citations do NOT carry the chunk's full text — only its identifiers,
  byte offsets, score, and source-strategy attribution; the grounding
  fragments carry the text. Two separate concerns.
"""

from app._deprecated.rag.citations.builder import build_citation_index
from app._deprecated.rag.citations.models import Citation, CitationIndex

__all__ = [
    "Citation",
    "CitationIndex",
    "build_citation_index",
]

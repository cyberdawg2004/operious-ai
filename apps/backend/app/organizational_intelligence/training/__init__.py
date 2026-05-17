"""Memory-evolution / training runtime.

Naming note: the directory is `training/` to mirror the brief's
suggested structure, but the substrate-internal name is
`MemoryEvolutionRuntime` — there are no "trainer agents" here.
The runtime is a deterministic pipeline that converts caller-
supplied observations into proposals and waits for human
approval.
"""

from app.organizational_intelligence.training.extractor import (
    DeterministicCandidateExtractor,
)
from app.organizational_intelligence.training.runtime import (
    MemoryEvolutionRuntime,
)

__all__ = [
    "DeterministicCandidateExtractor",
    "MemoryEvolutionRuntime",
]

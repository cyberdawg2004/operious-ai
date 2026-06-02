"""Constitutional repository layer.

Repositories are the persistence-access boundary. Their contract is
deliberately narrow:

* They encapsulate SQL / ORM queries for a single domain.
* They never commit, never rollback, never own transactions.
* They never call external systems, never know HTTP exists, never
  contain business policy.

Services own transactions and orchestrate one or more repositories;
this asymmetry is what keeps multi-step persistence work composable
without dragging in a unit-of-work framework.

Phase 2.1 cleanup note:

* `DocumentRepository`, `DocumentChunkRepository`,
  `ChunkEmbeddingRepository`, `WorkflowExecutionRepository`, and
  `TaskExecutionRepository` were removed with the legacy quarantine.
  Only `BaseRepository` (the abstract query base) and
  `SystemHealthRepository` (used by liveness probes) remain in the
  constitutional surface.
"""

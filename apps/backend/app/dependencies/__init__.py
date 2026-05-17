"""Constitutional FastAPI dependency providers.

Two small modules, each owning one wiring concern:

* `database` — async session + session factory.
* `services` — services composed from repositories and primitives.

Routers depend on `services` (and occasionally on a repository
directly for read-only auxiliary endpoints). Services and
repositories never import from this package — providers depend on
them, not the other way around.

Phase 2.1 quarantine note:

* `dependencies.orchestration`, `dependencies.governance` (legacy
  document/chunk-centric DI, NOT the constitutional governance
  substrate), `dependencies.memory`, `dependencies.rag`,
  `dependencies.providers`, and `dependencies.repositories` were
  quarantined under `app._deprecated.dependencies.*`. Constitutional
  substrate DI providers (session, governance, coordination,
  arbitration, boundary, organizational_intelligence) will land in
  Phase 2.4 and Phase 2.5, sourced from the request authority
  envelope.
"""

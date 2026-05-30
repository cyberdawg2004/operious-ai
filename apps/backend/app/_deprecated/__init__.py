"""Quarantine zone for pre-constitution platform code (Phase 2.1).

Every module under this package is **dead code from the legacy
"AI-native, orchestration-first, multi-agent" architecture** that the
constitution explicitly forbids:

* `_deprecated.orchestration`  — durable workflow / task engine
* `_deprecated.ai`             — AI gateway with autonomous retries
* `_deprecated.providers`      — vendor SDK adapters (OpenAI, etc.)
* `_deprecated.memory`         — ungoverned RAG memory pipeline
* `_deprecated.rag`            — ungoverned retrieval / assembly
* `_deprecated.embeddings`     — embedding gateway
* `_deprecated.repositories`   — legacy repositories (workflow / chunk)
* `_deprecated.db.models`      — legacy ORM tables
* `_deprecated.services`       — legacy service-layer entrypoints
* `_deprecated.dependencies`   — legacy DI providers
* `_deprecated.observability`  — legacy domain-specific log/metric
                                 emitters and the `audit` shim

These modules are kept on disk for:

* **Forensic evidence** — auditors and engineers can inspect what was
  excised, why, and when.
* **Rollback safety** — restoring any single module is a `git mv` away.
* **Migration safety** — the legacy Alembic migrations
  (`0002_create_workflow_task_execution_tables`,
  `0003_create_memory_documents_chunks_embeddings`) remain runnable so
  databases that already applied them stay consistent. A future
  Phase 5 migration will drop those tables; the modules here are
  decoupled from that lifecycle.

Strict rules (enforced by `tests/test_legacy_module_quarantine.py`):

1. NO module outside `app._deprecated.*` may import from
   `app._deprecated.*`. Any such import is a test failure.
2. NO module under `app._deprecated.*` may import from any
   constitutional substrate (`app.agents`, `app.governance`,
   `app.supervisor`, `app.coordination*`, `app.arbitration`,
   `app.boundary*`, `app.session`, `app.organizational_intelligence`,
   `app.hardening`, plus future `app.event_fabric`, `app.identity`).
   Quarantine is bidirectional.
3. NO new code may be added under `app._deprecated.*`. Existing files
   may only be deleted.

This package intentionally exposes nothing at the top level. Every
submodule must be addressed by its full dotted path so import-graph
auditors can detect each individual coupling.
"""

# No live code imports from this directory.
# Constitutional rule enforced by AST scan.

__all__: list[str] = []

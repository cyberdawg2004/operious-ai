"""Phase 2.1 quarantine helper — rewrites legacy imports inside `app/_deprecated/`.

Every quarantined module previously imported sibling legacy modules under
their original dotted paths (e.g. `from app.orchestration.foo import X`).
After the move, those references must point at `app._deprecated.<...>`
or the modules will fail at import time.

This script is intentionally narrow:

* It walks `apps/backend/app/_deprecated/` only.
* It rewrites a fixed list of legacy prefixes by prepending
  `_deprecated.` after `app.`.
* It rewrites both `from app.<prefix>` and `import app.<prefix>` forms.
* It is idempotent — running it twice is a no-op because the second pass
  matches no `app.<prefix>` (everything is now `app._deprecated.<prefix>`).
* It refuses to mutate anything outside `app/_deprecated/`.

Run from the backend root:

    python scripts/_phase21_rewrite_imports.py

The script is not part of the runtime; it is committed as forensic
evidence for the Phase 2.1 quarantine commit only.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

LEGACY_PREFIXES: tuple[str, ...] = (
    "orchestration",
    "ai",
    "providers",
    "memory",
    "rag",
    "embeddings",
    "repositories.document_repository",
    "repositories.document_chunk_repository",
    "repositories.chunk_embedding_repository",
    "repositories.workflow_execution_repository",
    "repositories.task_execution_repository",
    "services.orchestration_service",
    "services.ai_service",
    "dependencies.orchestration",
    "dependencies.governance",
    "dependencies.memory",
    "dependencies.rag",
    "dependencies.providers",
    "dependencies.repositories",
    "db.models.document",
    "db.models.document_chunk",
    "db.models.chunk_embedding",
    "db.models.workflow_execution",
    "db.models.task_execution",
    "observability.audit",
    "observability.ai_logging",
    "observability.ai_metrics",
    "observability.context_assembly_logging",
    "observability.context_assembly_metrics",
    "observability.embedding_logging",
    "observability.embedding_metrics",
    "observability.governance_logging",
    "observability.governance_metrics",
    "observability.orchestration_logging",
    "observability.orchestration_metrics",
    "observability.rag_retrieval_logging",
    "observability.rag_retrieval_metrics",
    "observability.retrieval_logging",
    "observability.retrieval_metrics",
)

# Targets that move INTO `_deprecated/governance_bridge/` rather than
# inheriting their original sub-path. `(legacy_dotted_path, replacement)`.
_GOVERNANCE_BRIDGE_REWRITES: tuple[tuple[str, str], ...] = (
    (
        "app.governance.subjects.factories",
        "app._deprecated.governance_bridge.subjects_factories",
    ),
    (
        "app.governance.guardrails",
        "app._deprecated.governance_bridge.guardrails",
    ),
)


def _build_patterns() -> list[tuple[re.Pattern[str], str]]:
    patterns: list[tuple[re.Pattern[str], str]] = []
    for prefix in LEGACY_PREFIXES:
        escaped = re.escape(prefix)
        patterns.append(
            (
                re.compile(rf"\bfrom app\.{escaped}\b"),
                f"from app._deprecated.{prefix}",
            )
        )
        patterns.append(
            (
                re.compile(rf"\bimport app\.{escaped}\b"),
                f"import app._deprecated.{prefix}",
            )
        )
    for original, replacement in _GOVERNANCE_BRIDGE_REWRITES:
        escaped = re.escape(original)
        patterns.append(
            (
                re.compile(rf"\bfrom {escaped}\b"),
                f"from {replacement}",
            )
        )
        patterns.append(
            (
                re.compile(rf"\bimport {escaped}\b"),
                f"import {replacement}",
            )
        )
    return patterns


def _rewrite(path: Path, patterns: list[tuple[re.Pattern[str], str]]) -> bool:
    original = path.read_text(encoding="utf-8")
    rewritten = original
    for pattern, replacement in patterns:
        rewritten = pattern.sub(replacement, rewritten)
    if rewritten == original:
        return False
    path.write_text(rewritten, encoding="utf-8")
    return True


def main(root: Path) -> int:
    deprecated_root = root / "app" / "_deprecated"
    if not deprecated_root.is_dir():
        print(f"refusing to run: {deprecated_root} is not a directory", file=sys.stderr)
        return 1

    patterns = _build_patterns()
    changed: list[Path] = []
    for path in deprecated_root.rglob("*.py"):
        if _rewrite(path, patterns):
            changed.append(path)

    print(f"rewrote {len(changed)} files under {deprecated_root}")
    for path in changed:
        print(f"  {path.relative_to(root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(__file__).resolve().parent.parent))

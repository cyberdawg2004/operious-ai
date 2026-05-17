"""Phase 2.1 — Legacy quarantine invariants.

This test file is the single, canonical guard that prevents the
pre-constitution architecture from contaminating the constitutional
substrates after the Phase 2.1 quarantine.

The contract is asymmetric and explicit:

1. **No constitutional or infrastructure module may import from
   `app._deprecated.*`.** Hard invariant.
   The legacy half is dead code on disk; importing it back would
   silently re-introduce orchestration / autonomous-agent semantics
   into the deterministic runtime.

2. **Legacy top-level package names (e.g. `app.orchestration`,
   `app.ai`, `app.providers`, `app.memory`, `app.rag`,
   `app.embeddings`) must not re-appear at the top level.** Hard
   invariant.

3. **Legacy → constitutional couplings are pinned.** Soft / forensic
   invariant.
   When the legacy half was quarantined, a small number of legacy
   modules already imported the constitutional `app.governance`
   substrate (the legacy DI wired its workflow engine through
   constitutional governance). Those couplings are pinned in
   `_LEGACY_TO_CONSTITUTIONAL_PINS` below. Any *new* legacy →
   constitutional import — or any new constitutional substrate ever
   touched by legacy code — fails the test. The contract is "this
   coupling must shrink, never grow"; deletion of `_deprecated/` (or
   of any individual legacy file) automatically removes its pin.

4. **Legacy code may otherwise import only from the
   `_deprecated.*` namespace plus a narrow infrastructure
   allow-list.** Hard invariant.

The combination of (1) and (3) means the production runtime never
reaches `_deprecated.*`, so even though legacy code transitively
references `app.governance.*`, those imports are never executed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_BACKEND_ROOT = Path(__file__).resolve().parent.parent
APP_ROOT = REPO_BACKEND_ROOT / "app"
DEPRECATED_ROOT = APP_ROOT / "_deprecated"
TESTS_ROOT = REPO_BACKEND_ROOT / "tests"

LEGACY_TOP_LEVEL_PACKAGE_NAMES: tuple[str, ...] = (
    "ai",
    "embeddings",
    "memory",
    "orchestration",
    "providers",
    "rag",
)

CONSTITUTIONAL_SUBSTRATE_PREFIXES: tuple[str, ...] = (
    "app.agents",
    "app.arbitration",
    "app.boundary",
    "app.coordination",
    "app.event_fabric",
    "app.governance",
    "app.hardening",
    "app.identity",
    "app.organizational_intelligence",
    "app.session",
    "app.supervisor",
    "app.supervision",
)

_FROM_OR_IMPORT_DEPRECATED = re.compile(
    r"^\s*(?:from|import)\s+app\._deprecated(\b|\.)",
    re.MULTILINE,
)

_FROM_OR_IMPORT_CONSTITUTIONAL = re.compile(
    r"^\s*(?:from|import)\s+app\.(?P<substrate>"
    + "|".join(
        re.escape(prefix.removeprefix("app."))
        for prefix in CONSTITUTIONAL_SUBSTRATE_PREFIXES
    )
    + r")(\b|\.)",
    re.MULTILINE,
)


def _python_files_under(path: Path) -> list[Path]:
    return sorted(p for p in path.rglob("*.py") if p.is_file())


def _python_files_outside_deprecated() -> list[Path]:
    files: list[Path] = []
    for path in APP_ROOT.rglob("*.py"):
        if not path.is_file():
            continue
        try:
            path.relative_to(DEPRECATED_ROOT)
        except ValueError:
            files.append(path)
    return sorted(files)


def _is_quarantine_doc(path: Path) -> bool:
    """Allow this single test file (and the audit doc it pins) to mention
    `app._deprecated` in regex-pattern form without counting as an import.
    """
    return path.resolve() == Path(__file__).resolve()


# ─── Invariant 1: outside code never imports from `_deprecated` ────────


def test_no_app_module_imports_from_deprecated() -> None:
    offences: list[str] = []
    for path in _python_files_outside_deprecated():
        if _is_quarantine_doc(path):
            continue
        text = path.read_text(encoding="utf-8")
        for match in _FROM_OR_IMPORT_DEPRECATED.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            offences.append(f"{path.relative_to(REPO_BACKEND_ROOT)}:{line}")
    assert not offences, (
        "constitutional code must never import from app._deprecated; "
        "found imports at: " + ", ".join(offences)
    )


def test_no_test_module_imports_from_deprecated() -> None:
    offences: list[str] = []
    for path in _python_files_under(TESTS_ROOT):
        if _is_quarantine_doc(path):
            continue
        text = path.read_text(encoding="utf-8")
        for match in _FROM_OR_IMPORT_DEPRECATED.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            offences.append(f"{path.relative_to(REPO_BACKEND_ROOT)}:{line}")
    assert not offences, (
        "tests must never import from app._deprecated; "
        "found imports at: " + ", ".join(offences)
    )


# ─── Invariant 3: legacy → constitutional coupling is pinned ──────────


# Pinned set of `(legacy_relpath, constitutional_substrate)` couplings
# that existed at quarantine time. Pins shrink (never grow) over time:
# every removed legacy file removes its pin automatically.
_LEGACY_TO_CONSTITUTIONAL_PINS: frozenset[tuple[str, str]] = frozenset(
    {
        ("app/_deprecated/dependencies/governance.py", "governance"),
        (
            "app/_deprecated/orchestration/tasks/governed_context_assembly_task.py",
            "governance",
        ),
        (
            "app/_deprecated/governance_bridge/subjects_factories.py",
            "governance",
        ),
        (
            "app/_deprecated/governance_bridge/guardrails/adapters.py",
            "governance",
        ),
    }
)


def test_legacy_to_constitutional_couplings_are_pinned() -> None:
    if not DEPRECATED_ROOT.is_dir():
        pytest.skip("app/_deprecated/ not present")
    observed: set[tuple[str, str]] = set()
    for path in _python_files_under(DEPRECATED_ROOT):
        text = path.read_text(encoding="utf-8")
        rel = str(path.relative_to(REPO_BACKEND_ROOT))
        for match in _FROM_OR_IMPORT_CONSTITUTIONAL.finditer(text):
            substrate = match.group("substrate")
            top = substrate.split(".", 1)[0]
            observed.add((rel, top))

    new_couplings = observed - _LEGACY_TO_CONSTITUTIONAL_PINS
    assert not new_couplings, (
        "new legacy → constitutional couplings detected — quarantine "
        "must shrink, never grow. New couplings: "
        + ", ".join(f"{f} -> app.{s}" for f, s in sorted(new_couplings))
    )

    stale_pins = _LEGACY_TO_CONSTITUTIONAL_PINS - observed
    assert not stale_pins, (
        "stale pin(s) in _LEGACY_TO_CONSTITUTIONAL_PINS — remove from "
        "the pin list because the underlying file or import is gone: "
        + ", ".join(f"{f} -> app.{s}" for f, s in sorted(stale_pins))
    )


# ─── Invariant 2: legacy top-level package names do not re-appear ──────


def test_legacy_top_level_packages_remain_quarantined() -> None:
    offenders: list[str] = []
    for legacy in LEGACY_TOP_LEVEL_PACKAGE_NAMES:
        candidate = APP_ROOT / legacy
        if candidate.exists():
            offenders.append(str(candidate.relative_to(REPO_BACKEND_ROOT)))
    assert not offenders, (
        "legacy top-level packages must remain under app/_deprecated/; "
        "found at: " + ", ".join(offenders)
    )


# ─── Invariant 4: deprecated files import only from infra + pinned ──


_ALLOWED_RUNTIME_PREFIXES_FOR_DEPRECATED: tuple[str, ...] = (
    "app._deprecated.",
    "app.core.",
    "app.db.base",
    "app.db.session",
    "app.db.__init__",
    "app.db.models.system_health",
    "app.observability.context",
    "app.observability.logging",
    "app.observability.audit",
    "app.middleware.",
    "app.repositories.base",
    "app.repositories.system_health_repository",
    "app.services.base",
    "app.services.health_service",
    "app.dependencies.database",
    "app.dependencies.services",
    "app.api.",
)


_FROM_OR_IMPORT_APP = re.compile(
    r"^\s*(?:from|import)\s+(app(?:\.[A-Za-z_][A-Za-z0-9_]*)+)",
    re.MULTILINE,
)


def _coupling_is_pinned(file_relpath: str, target: str) -> bool:
    """Return True if `from <target>` inside `<file_relpath>` is allowed
    by the pinned legacy → constitutional coupling list (Invariant 3).
    """
    if not target.startswith("app."):
        return False
    top = target.removeprefix("app.").split(".", 1)[0]
    return (file_relpath, top) in _LEGACY_TO_CONSTITUTIONAL_PINS


def test_deprecated_modules_import_only_from_themselves_or_infra() -> None:
    """Deprecated code may import:

    * `app._deprecated.*` (its own siblings),
    * a narrow infrastructure allow-list (request-id ContextVar,
      settings, logging filter, base classes, health surfaces),
    * the constitutional substrates explicitly pinned in
      `_LEGACY_TO_CONSTITUTIONAL_PINS`.

    Anything else inside `app.*` is forbidden so deprecated code
    cannot silently grow new coupling into constitutional substrates
    or into the new event-fabric / identity layers landing in
    Phase 2.3 / 2.4.
    """
    if not DEPRECATED_ROOT.is_dir():
        pytest.skip("app/_deprecated/ not present")
    offences: list[str] = []
    for path in _python_files_under(DEPRECATED_ROOT):
        text = path.read_text(encoding="utf-8")
        rel = str(path.relative_to(REPO_BACKEND_ROOT))
        for match in _FROM_OR_IMPORT_APP.finditer(text):
            target = match.group(1)
            if any(
                target == prefix.rstrip(".")
                or target.startswith(prefix)
                for prefix in _ALLOWED_RUNTIME_PREFIXES_FOR_DEPRECATED
            ):
                continue
            if _coupling_is_pinned(rel, target):
                continue
            line = text.count("\n", 0, match.start()) + 1
            offences.append(f"{rel}:{line} (forbidden import: {target})")
    assert not offences, (
        "deprecated modules may only import from `app._deprecated.*`, "
        "from a narrow infrastructure allow-list, or via pinned "
        "legacy→constitutional couplings; offending imports: "
        + "; ".join(offences)
    )

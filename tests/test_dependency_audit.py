"""Phase 5 — dependency-graph audit (executable form).

These are not behaviour tests. They are STATIC checks that fail loudly if
the project's import boundaries regress. They exist because architecture
documents are only worth as much as they are enforced.

Checks:

1. The vendor-SDK firewall: `openai` (and any future vendor SDK) MUST only
   be imported by `app/providers/*_provider.py` files. Anything else
   touching a vendor SDK is a boundary violation.

2. Memory subsystem isolation: nothing under `app/memory/` may import
   vendor SDKs OR concrete provider classes.

3. Orchestration tasks remain thin adapters: a task module may only
   import from `app.services`, `app.memory`, `app.providers.models`-style
   shape modules, `app.orchestration.*`, stdlib, and typing.

4. Repositories must not import workflow / orchestration runtime / service
   modules — only stdlib, SQLAlchemy, `app.db.*`, `app.orchestration.enums`
   (for the persisted enum vocabulary), and `app.repositories.*`.

5. Chunkers must be pure: no SQLAlchemy, no providers, no observability.

Each failure points the reader at the specific file + offending import so
the violation can be fixed in one place.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterable, Sequence

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_APP_ROOT = _REPO_ROOT / "app"


def _iter_py_files(root: Path, exclude: Iterable[str] = ()) -> list[Path]:
    excluded = {Path(_APP_ROOT, e) for e in exclude}
    return [
        p
        for p in root.rglob("*.py")
        if p.is_file()
        and "__pycache__" not in p.parts
        and not any(p.is_relative_to(x) for x in excluded)
    ]


def _imports_of(path: Path) -> list[str]:
    """Return every dotted import path mentioned in `path`."""

    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module is not None:
                names.append(node.module)
    return names


# ─── 1. Vendor-SDK firewall ───────────────────────────────────────────────


_VENDOR_SDKS = ("openai", "anthropic", "cohere", "huggingface_hub", "pinecone")
_PROVIDER_FILES = {
    "openai_provider.py",
    "openai_embedding_provider.py",
}


def test_vendor_sdks_only_imported_inside_provider_layer() -> None:
    offenders: list[tuple[str, str]] = []
    for path in _iter_py_files(_APP_ROOT):
        if path.name in _PROVIDER_FILES:
            continue
        imports = _imports_of(path)
        for imp in imports:
            head = imp.split(".", 1)[0]
            if head in _VENDOR_SDKS:
                offenders.append((str(path.relative_to(_REPO_ROOT)), imp))
    assert not offenders, (
        "Vendor SDKs may only be imported by provider implementation files. "
        f"Offenders: {offenders}"
    )


# ─── 2. Memory subsystem isolation ────────────────────────────────────────


_FORBIDDEN_FOR_MEMORY = (
    # Concrete providers — memory consumes the abstract base classes only.
    "app.providers.openai_provider",
    "app.providers.openai_embedding_provider",
    "app.providers.in_memory_vector_provider",
)


def test_memory_subsystem_does_not_import_concrete_providers() -> None:
    offenders: list[tuple[str, str]] = []
    for path in _iter_py_files(_APP_ROOT / "memory"):
        for imp in _imports_of(path):
            if imp in _FORBIDDEN_FOR_MEMORY:
                offenders.append((str(path.relative_to(_REPO_ROOT)), imp))
    assert not offenders, (
        "Memory modules must depend on abstract providers (BaseEmbeddingProvider,"
        " BaseVectorProvider) and let the DI layer wire concretes. "
        f"Offenders: {offenders}"
    )


def test_memory_subsystem_does_not_import_vendor_sdks() -> None:
    offenders: list[tuple[str, str]] = []
    for path in _iter_py_files(_APP_ROOT / "memory"):
        for imp in _imports_of(path):
            head = imp.split(".", 1)[0]
            if head in _VENDOR_SDKS:
                offenders.append((str(path.relative_to(_REPO_ROOT)), imp))
    assert not offenders, f"Memory layer leaked vendor SDK import: {offenders}"


# ─── 3. Orchestration tasks stay thin ─────────────────────────────────────


def test_orchestration_tasks_dont_import_providers_or_gateways_directly() -> None:
    """Tasks must consume services / memory APIs, NOT gateways or providers.

    Concretely, no task may import `app.ai.gateway`, `app.embeddings.gateway`,
    or any concrete provider — the orchestration layer's contract is the
    *service* layer.
    """

    forbidden = {
        "app.ai.gateway",
        "app.embeddings.gateway",
        "app.providers.openai_provider",
        "app.providers.openai_embedding_provider",
        "app.providers.in_memory_vector_provider",
        "app.providers.registry",
        "app.providers.embedding_registry",
        "app.providers.vector_registry",
    }
    offenders: list[tuple[str, str]] = []
    for path in _iter_py_files(_APP_ROOT / "orchestration" / "tasks"):
        for imp in _imports_of(path):
            if imp in forbidden:
                offenders.append((str(path.relative_to(_REPO_ROOT)), imp))
    assert not offenders, (
        "Orchestration tasks must remain thin adapters and consume services, "
        f"not infrastructure primitives. Offenders: {offenders}"
    )


# ─── 4. Repositories isolation ────────────────────────────────────────────


def test_repositories_do_not_import_workflows_runtime_or_services() -> None:
    forbidden_prefixes = (
        "app.orchestration.runtime",
        "app.orchestration.workflows",
        "app.orchestration.tasks",
        "app.services.",
        "app.memory.",
        "app.embeddings.",
        "app.ai.",
    )
    offenders: list[tuple[str, str]] = []
    for path in _iter_py_files(_APP_ROOT / "repositories"):
        for imp in _imports_of(path):
            for prefix in forbidden_prefixes:
                if imp == prefix.rstrip(".") or imp.startswith(prefix):
                    offenders.append((str(path.relative_to(_REPO_ROOT)), imp))
                    break
    assert not offenders, (
        "Repositories must depend only on app.db, SQLAlchemy, stdlib, and the "
        "narrow orchestration.enums vocabulary. "
        f"Offenders: {offenders}"
    )


# ─── 5. Chunkers are pure ─────────────────────────────────────────────────


def test_chunkers_have_no_io_or_provider_imports() -> None:
    forbidden_prefixes = (
        "sqlalchemy",
        "app.db.",
        "app.providers.",
        "app.repositories.",
        "app.observability.",
        "app.embeddings.",
        "fastapi",
        "starlette",
        "openai",
        "anthropic",
        "redis",
    )
    offenders: list[tuple[str, str]] = []
    for path in _iter_py_files(_APP_ROOT / "memory" / "chunking"):
        for imp in _imports_of(path):
            for prefix in forbidden_prefixes:
                if imp == prefix.rstrip(".") or imp.startswith(prefix):
                    offenders.append((str(path.relative_to(_REPO_ROOT)), imp))
                    break
    assert not offenders, (
        "Chunkers must be pure functions of (text, config). Any I/O or "
        f"infrastructure import is a violation. Offenders: {offenders}"
    )


# ─── 6. No circular imports at top level ──────────────────────────────────


def test_full_application_imports_without_error() -> None:
    """If any module has a circular import or a typo, this fails fast.

    Importing `app.main` transitively imports every wired-in module in
    the production runtime."""

    # Set fake DATABASE_URL so the production engine can be constructed
    # without contacting a real DB.
    import os

    os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    os.environ.setdefault("OPENAI_API_KEY", "")
    import importlib

    importlib.import_module("app.main")


# ─── 7. AI gateway uses abstract registry, not concrete providers ─────────


def test_ai_gateway_module_does_not_import_concrete_providers() -> None:
    concretes = {
        "app.providers.openai_provider",
        "app.providers.openai_embedding_provider",
    }
    offenders: list[str] = []
    for path in _iter_py_files(_APP_ROOT / "ai"):
        for imp in _imports_of(path):
            if imp in concretes:
                offenders.append(f"{path.relative_to(_REPO_ROOT)} → {imp}")
    assert not offenders, (
        "The AI gateway must consume `ProviderRegistry` abstractly; never "
        f"import concrete providers. Offenders: {offenders}"
    )


# ─── 8. Embeddings subsystem uses abstract registry, not concrete impls ───


def test_embedding_subsystem_does_not_import_concrete_providers() -> None:
    concretes = {
        "app.providers.openai_provider",
        "app.providers.openai_embedding_provider",
    }
    offenders: list[str] = []
    for path in _iter_py_files(_APP_ROOT / "embeddings"):
        for imp in _imports_of(path):
            if imp in concretes:
                offenders.append(f"{path.relative_to(_REPO_ROOT)} → {imp}")
    assert not offenders, (
        "The embedding gateway must consume `EmbeddingProviderRegistry` "
        f"abstractly. Offenders: {offenders}"
    )


# ─── 9. RAG layer respects the provider firewall ─────────────────────────


def test_rag_layer_does_not_import_vendor_sdks() -> None:
    offenders: list[tuple[str, str]] = []
    for path in _iter_py_files(_APP_ROOT / "rag"):
        for imp in _imports_of(path):
            head = imp.split(".", 1)[0]
            if head in _VENDOR_SDKS:
                offenders.append((str(path.relative_to(_REPO_ROOT)), imp))
    assert not offenders, (
        "The RAG layer is pure runtime infrastructure and may not import "
        f"vendor SDKs. Offenders: {offenders}"
    )


def test_rag_layer_does_not_import_concrete_providers() -> None:
    concretes = {
        "app.providers.openai_provider",
        "app.providers.openai_embedding_provider",
        "app.providers.in_memory_vector_provider",
    }
    offenders: list[str] = []
    for path in _iter_py_files(_APP_ROOT / "rag"):
        for imp in _imports_of(path):
            if imp in concretes:
                offenders.append(f"{path.relative_to(_REPO_ROOT)} → {imp}")
    assert not offenders, (
        "RAG strategies must compose services (RetrievalService) — never "
        f"concrete providers. Offenders: {offenders}"
    )


# ─── 10. RAG sub-package layering ─────────────────────────────────────────


def test_rag_lower_layers_do_not_import_upper_layers() -> None:
    """Pin the one-way dependency direction inside `app/rag/`.

    Allowed cross-package imports are vocabulary-only (frozen-dataclass
    `models` modules). The orchestration / runtime / service / builder
    modules of an upper layer are off-limits to lower layers.

    Conceptual layering (low → high):

        policies, citations/models, retrieval/models  ← vocabulary
        retrieval (runtime + strategies)
        reranking
        budgeting
        citations (builder + index)
        grounding
        assembly (apex)
    """
    # Each entry lists the "upper" sub-packages whose runtime modules
    # the listed lower package may not import. `models` modules are
    # always allowed because they are pure type vocabulary.
    forbidden_runtime_modules = {
        "policies":   {"app.rag.assembly", "app.rag.grounding",
                       "app.rag.budgeting", "app.rag.reranking",
                       "app.rag.retrieval.runtime",
                       "app.rag.retrieval.single_query",
                       "app.rag.retrieval.base",
                       "app.rag.citations.builder"},
        "citations":  {"app.rag.assembly", "app.rag.grounding",
                       "app.rag.budgeting", "app.rag.reranking",
                       "app.rag.retrieval.runtime",
                       "app.rag.retrieval.single_query",
                       "app.rag.retrieval.base"},
        "budgeting":  {"app.rag.assembly", "app.rag.grounding",
                       "app.rag.reranking", "app.rag.citations.builder",
                       "app.rag.retrieval.runtime",
                       "app.rag.retrieval.single_query",
                       "app.rag.retrieval.base"},
        "retrieval":  {"app.rag.assembly", "app.rag.grounding",
                       "app.rag.reranking", "app.rag.budgeting",
                       "app.rag.citations"},
        "reranking":  {"app.rag.assembly", "app.rag.grounding",
                       "app.rag.budgeting", "app.rag.citations.builder",
                       "app.rag.retrieval.runtime",
                       "app.rag.retrieval.single_query",
                       "app.rag.retrieval.base"},
        "grounding":  {"app.rag.assembly", "app.rag.reranking",
                       "app.rag.budgeting",
                       "app.rag.retrieval.runtime",
                       "app.rag.retrieval.single_query",
                       "app.rag.retrieval.base"},
    }

    offenders: list[str] = []
    for sub_pkg, forbidden in forbidden_runtime_modules.items():
        sub_root = _APP_ROOT / "rag" / sub_pkg
        if not sub_root.exists():
            continue
        for path in _iter_py_files(sub_root):
            for imp in _imports_of(path):
                for prefix in forbidden:
                    if imp == prefix or imp.startswith(prefix + "."):
                        offenders.append(
                            f"{path.relative_to(_REPO_ROOT)} → {imp}"
                        )
                        break
    assert not offenders, (
        "RAG sub-packages must respect one-way layering. Vocabulary "
        "(`models` modules) is shared; runtime/service modules of upper "
        f"layers are off-limits to lower layers. Offenders: {offenders}"
    )


# ─── 12. Governance layer respects the provider firewall ────────────────


def test_governance_layer_does_not_import_vendor_sdks() -> None:
    offenders: list[tuple[str, str]] = []
    for path in _iter_py_files(_APP_ROOT / "governance"):
        for imp in _imports_of(path):
            head = imp.split(".", 1)[0]
            if head in _VENDOR_SDKS:
                offenders.append((str(path.relative_to(_REPO_ROOT)), imp))
    assert not offenders, (
        "The governance substrate is pure runtime infrastructure and may "
        f"not import vendor SDKs. Offenders: {offenders}"
    )


def test_governance_layer_does_not_import_concrete_providers() -> None:
    concretes = {
        "app.providers.openai_provider",
        "app.providers.openai_embedding_provider",
        "app.providers.in_memory_vector_provider",
    }
    offenders: list[str] = []
    for path in _iter_py_files(_APP_ROOT / "governance"):
        for imp in _imports_of(path):
            if imp in concretes:
                offenders.append(f"{path.relative_to(_REPO_ROOT)} → {imp}")
    assert not offenders, (
        "Governance must depend on substrate vocabulary only — never on "
        f"concrete providers. Offenders: {offenders}"
    )


# ─── 13. Governance substrate does not reach into RAG / memory ──────────


def test_governance_substrate_does_not_import_rag_or_memory_runtimes() -> None:
    """The substrate is a LEAF in the dependency graph.

    Two bounded integration files may import Sprint H types:

    * `app/governance/guardrails/*` — runtime composition
      (`GovernedAssemblyRuntime`),
    * `app/governance/subjects/factories.py` — typed-subject
      construction from operational types.

    Everything else under `app/governance/` MUST be unaware of RAG
    and memory entirely — `subjects/{base,retrieval,execution,
    agent_actions,communication}.py` MUST stay import-clean so the
    vocabulary is reusable by replay tools / persistence consumers
    that may not have Sprint H available.
    """
    forbidden_prefixes = (
        "app.rag",
        "app.memory",
        "app.embeddings",
        "app.ai",
    )
    offenders: list[str] = []
    for path in _iter_py_files(_APP_ROOT / "governance"):
        # Two bounded integration paths are permitted.
        if "guardrails" in path.parts:
            continue
        if path.name == "factories.py" and "subjects" in path.parts:
            continue
        for imp in _imports_of(path):
            for prefix in forbidden_prefixes:
                if imp == prefix or imp.startswith(prefix + "."):
                    offenders.append(f"{path.relative_to(_REPO_ROOT)} → {imp}")
                    break
    assert not offenders, (
        "Governance substrate (outside `guardrails/` and "
        "`subjects/factories.py`) must be a LEAF — RAG / memory / "
        "embeddings / AI runtime imports are confined to those two "
        f"bounded integration files. Offenders: {offenders}"
    )


# ─── 13b. Subject vocabulary stays Sprint-H-clean ───────────────────────


def test_governance_subject_vocabulary_is_import_clean() -> None:
    """Typed subject value objects (base / retrieval / execution /
    agent_actions / communication) MUST NOT import Sprint H runtime
    types. The vocabulary is reusable by replay tools / persistence
    consumers that may not have Sprint H available; coupling here
    would break that property.

    `subjects/factories.py` is the exception — its job IS to convert
    operational types into subjects.
    """
    forbidden_prefixes = ("app.rag", "app.memory", "app.embeddings", "app.ai")
    offenders: list[str] = []
    subjects_dir = _APP_ROOT / "governance" / "subjects"
    for path in _iter_py_files(subjects_dir):
        if path.name == "factories.py":
            continue
        for imp in _imports_of(path):
            for prefix in forbidden_prefixes:
                if imp == prefix or imp.startswith(prefix + "."):
                    offenders.append(f"{path.relative_to(_REPO_ROOT)} → {imp}")
                    break
    assert not offenders, (
        "Governance subject vocabulary must be Sprint-H-clean. "
        "Operational-type translation belongs in `factories.py`. "
        f"Offenders: {offenders}"
    )


# ─── 13c. Persistence layer is ORM-free / storage-agnostic ──────────────


def test_governance_persistence_layer_is_storage_agnostic() -> None:
    """The persistence package defines CONTRACTS only.

    Forbidden imports (would couple to a specific storage backend):

    * `sqlalchemy`           — ORM coupling,
    * `asyncpg` / `psycopg2` — PG-driver coupling,
    * `app.repositories.*`   — runtime repository coupling,
    * `app.db.*`             — session / engine coupling,
    * `app.models.*`         — ORM-mapped model coupling.

    The in-memory reference repository under `persistence/memory.py`
    is exempt for the obvious reason — it implements the contract.
    Future production backends ship in new modules behind the same
    Protocol; this rule keeps the contract module clean.
    """
    forbidden_prefixes = (
        "sqlalchemy",
        "asyncpg",
        "psycopg2",
        "app.repositories",
        "app.db",
        "app.models",
    )
    offenders: list[str] = []
    persistence_dir = _APP_ROOT / "governance" / "persistence"
    for path in _iter_py_files(persistence_dir):
        for imp in _imports_of(path):
            head = imp.split(".", 1)[0]
            for prefix in forbidden_prefixes:
                if imp == prefix or imp.startswith(prefix + "."):
                    offenders.append(f"{path.relative_to(_REPO_ROOT)} → {imp}")
                    break
            # Also catch single-token vendor SDK imports we missed.
            if head in {"sqlalchemy", "asyncpg", "psycopg2"}:
                offenders.append(f"{path.relative_to(_REPO_ROOT)} → {imp}")
    assert not offenders, (
        "Governance persistence is contracts only — no ORM, DB driver, "
        f"or runtime repository coupling. Offenders: {offenders}"
    )


# ─── 13d. Typed-subject discipline at integration boundary ──────────────


def test_governed_assembly_runtime_uses_typed_subject_factories() -> None:
    """`GovernedAssemblyRuntime` must build subjects via the typed
    factories, never via dict literals. Lints against the loose
    `subject={...}` pattern that Sprint I (pre-hardening) used.
    """
    import re as _re

    adapter = _APP_ROOT / "governance" / "guardrails" / "adapters.py"
    src = adapter.read_text(encoding="utf-8")
    # Forbid `subject={` followed by anything other than the typed
    # factory call. This is a structural assertion — we expect the
    # `subject=` arg to receive a factory function call result.
    bad = _re.findall(r"subject=\{", src)
    assert not bad, (
        "GovernedAssemblyRuntime must use typed subject factories, "
        f"not dict literals. Found {len(bad)} dict-literal `subject=` "
        "usages in `guardrails/adapters.py`."
    )


# ─── 14. Governance never raises freeform exceptions ────────────────────


def test_governance_substrate_only_raises_typed_governance_errors() -> None:
    """Every `raise X(...)` inside the substrate must use a class from
    `app.governance.exceptions` or a stdlib built-in (`ValueError`,
    `KeyError`, etc. — allowed for narrow internal sanity checks).

    The check is structural — we scan `raise <NAME>(...)` AST nodes and
    require <NAME> to either be a stdlib built-in OR start with
    `Governance` / `Policy` / `Enforcement` (the substrate's typed
    error vocabulary).
    """
    import ast as _ast

    allowed_stdlib = {
        "ValueError",
        "KeyError",
        "RuntimeError",
        "TypeError",
        "NotImplementedError",
    }
    allowed_governance_prefixes = (
        "Governance",
        "Policy",
        "Enforcement",
    )
    offenders: list[str] = []
    for path in _iter_py_files(_APP_ROOT / "governance"):
        tree = _ast.parse(path.read_text(encoding="utf-8"))
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Raise) and node.exc is not None:
                call = node.exc
                # Unwrap Call(name, ...) into the name.
                if isinstance(call, _ast.Call):
                    name = (
                        call.func.id
                        if isinstance(call.func, _ast.Name)
                        else (
                            call.func.attr
                            if isinstance(call.func, _ast.Attribute)
                            else None
                        )
                    )
                elif isinstance(call, _ast.Name):
                    name = call.id
                else:
                    name = None
                if name is None:
                    continue
                if name in allowed_stdlib:
                    continue
                if any(name.startswith(p) for p in allowed_governance_prefixes):
                    continue
                offenders.append(
                    f"{path.relative_to(_REPO_ROOT)}:{node.lineno} → raise {name}"
                )
    assert not offenders, (
        "Governance substrate may only raise typed Governance/Policy/"
        "Enforcement errors or narrow stdlib errors. "
        f"Offenders: {offenders}"
    )


# ─── 16. Agent substrate is a LEAF (Sprint J) ────────────────────────────


def test_agents_layer_does_not_import_vendor_sdks() -> None:
    """Sprint J: substrate is pure runtime infrastructure."""
    offenders: list[tuple[str, str]] = []
    for path in _iter_py_files(_APP_ROOT / "agents"):
        for imp in _imports_of(path):
            head = imp.split(".", 1)[0]
            if head in _VENDOR_SDKS:
                offenders.append((str(path.relative_to(_REPO_ROOT)), imp))
    assert not offenders, (
        "The agent substrate is pure runtime infrastructure and may not "
        f"import vendor SDKs. Offenders: {offenders}"
    )


def test_agents_layer_does_not_import_concrete_providers() -> None:
    concretes = {
        "app.providers.openai_provider",
        "app.providers.openai_embedding_provider",
        "app.providers.in_memory_vector_provider",
    }
    offenders: list[str] = []
    for path in _iter_py_files(_APP_ROOT / "agents"):
        for imp in _imports_of(path):
            if imp in concretes:
                offenders.append(f"{path.relative_to(_REPO_ROOT)} → {imp}")
    assert not offenders, (
        "Agents substrate must depend on substrate vocabulary only — never "
        f"on concrete providers. Offenders: {offenders}"
    )


def test_agents_substrate_does_not_import_rag_or_memory_runtimes() -> None:
    """The agent substrate is a LEAF in the dependency graph.

    Tools wired into a deployment may legitimately depend on RAG /
    memory / embeddings (a `RetrievalTool` calls `RetrievalService`),
    but those concrete tools live OUTSIDE the substrate package — the
    substrate ships only `BaseTool` + the runtime around it. Anything
    under `app/agents/` MUST be unaware of RAG / memory / embeddings /
    AI runtime entirely.

    Governance integration is the one cross-substrate import — the
    agent runtime's tool invoker composes `GovernanceRuntime`. That
    is permitted and locked at the bridge module
    (`app/agents/tools/invoker.py`).
    """
    forbidden_prefixes = (
        "app.rag",
        "app.memory",
        "app.embeddings",
        "app.ai",
    )
    offenders: list[str] = []
    for path in _iter_py_files(_APP_ROOT / "agents"):
        for imp in _imports_of(path):
            for prefix in forbidden_prefixes:
                if imp == prefix or imp.startswith(prefix + "."):
                    offenders.append(f"{path.relative_to(_REPO_ROOT)} → {imp}")
                    break
    assert not offenders, (
        "Agents substrate must be a LEAF — RAG / memory / embeddings / "
        "AI runtime imports are not permitted. Concrete tools that need "
        "those subsystems live OUTSIDE the substrate. "
        f"Offenders: {offenders}"
    )


def test_agents_persistence_layer_is_storage_agnostic() -> None:
    """The agent persistence package defines CONTRACTS only.

    Same discipline as `app/governance/persistence/` — no ORM, no
    DB drivers, no runtime-repository coupling. Future production
    backends ship in new modules behind the same Protocol.
    """
    forbidden_prefixes = (
        "sqlalchemy",
        "asyncpg",
        "psycopg2",
        "app.repositories",
        "app.db",
        "app.models",
    )
    offenders: list[str] = []
    persistence_dir = _APP_ROOT / "agents" / "persistence"
    for path in _iter_py_files(persistence_dir):
        for imp in _imports_of(path):
            head = imp.split(".", 1)[0]
            for prefix in forbidden_prefixes:
                if imp == prefix or imp.startswith(prefix + "."):
                    offenders.append(f"{path.relative_to(_REPO_ROOT)} → {imp}")
                    break
            if head in {"sqlalchemy", "asyncpg", "psycopg2"}:
                offenders.append(f"{path.relative_to(_REPO_ROOT)} → {imp}")
    assert not offenders, (
        "Agent persistence is contracts only — no ORM, DB driver, or "
        f"runtime repository coupling. Offenders: {offenders}"
    )


def test_agents_substrate_only_raises_typed_agent_errors() -> None:
    """Every `raise` inside `app/agents/` uses a class from
    `app.agents.exceptions` or a narrow stdlib built-in.

    Mirrors the governance discipline: closed exception vocabulary so
    callers can pattern-match on typed errors.
    """
    import ast as _ast

    allowed_stdlib = {
        "ValueError",
        "KeyError",
        "RuntimeError",
        "TypeError",
        "NotImplementedError",
    }
    allowed_agent_prefixes = ("Agent", "Tool", "State", "Capability", "Constraint")
    offenders: list[str] = []
    for path in _iter_py_files(_APP_ROOT / "agents"):
        tree = _ast.parse(path.read_text(encoding="utf-8"))
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Raise) and node.exc is not None:
                call = node.exc
                if isinstance(call, _ast.Call):
                    name = (
                        call.func.id
                        if isinstance(call.func, _ast.Name)
                        else (
                            call.func.attr
                            if isinstance(call.func, _ast.Attribute)
                            else None
                        )
                    )
                elif isinstance(call, _ast.Name):
                    name = call.id
                else:
                    name = None
                if name is None:
                    continue
                if name in allowed_stdlib:
                    continue
                if any(name.startswith(p) for p in allowed_agent_prefixes):
                    continue
                offenders.append(
                    f"{path.relative_to(_REPO_ROOT)}:{node.lineno} → raise {name}"
                )
    assert not offenders, (
        "Agents substrate may only raise typed Agent/Tool/State/Capability/"
        "Constraint errors or narrow stdlib errors. "
        f"Offenders: {offenders}"
    )


def test_agents_runtime_does_not_import_governance_internals() -> None:
    """Governance integration is bounded to `app/agents/tools/invoker.py`.

    The agent runtime layer (`app/agents/runtime/*`) and every other
    substrate module MUST NOT import governance directly. The invoker
    is the single integration seam.
    """
    offenders: list[str] = []
    for path in _iter_py_files(_APP_ROOT / "agents"):
        # The invoker IS the bounded integration seam.
        if path.name == "invoker.py" and "tools" in path.parts:
            continue
        # Envelopes carry GovernanceEnvelope as a typed field — that's
        # vocabulary, not coupling.
        if path.name == "envelopes.py":
            continue
        for imp in _imports_of(path):
            if imp.startswith("app.governance"):
                offenders.append(f"{path.relative_to(_REPO_ROOT)} → {imp}")
    assert not offenders, (
        "Governance integration is confined to "
        "`app/agents/tools/invoker.py` (and envelope vocabulary in "
        "`app/agents/envelopes.py`). Other substrate modules must "
        f"compose, not import. Offenders: {offenders}"
    )


# ─── 15. RAG retrieval runtime does not reach vector providers ──────────


def test_rag_retrieval_does_not_touch_vector_or_embedding_gateways() -> None:
    """Strategies must compose `RetrievalService` — never bypass it."""
    forbidden = {
        "app.providers.vector_base",
        "app.providers.vector_models",
        "app.providers.vector_registry",
        "app.embeddings.gateway",
    }
    offenders: list[str] = []
    for path in _iter_py_files(_APP_ROOT / "rag" / "retrieval"):
        for imp in _imports_of(path):
            if imp in forbidden:
                offenders.append(f"{path.relative_to(_REPO_ROOT)} → {imp}")
    # `app.embeddings.tracing` is allowed — it is a model/trace type
    # rebroadcast onto the retrieval-runtime trace; it is not the gateway.
    assert not offenders, (
        "RAG retrieval strategies must compose `RetrievalService` and "
        f"must not bypass into the vector / embedding gateway. Offenders: {offenders}"
    )

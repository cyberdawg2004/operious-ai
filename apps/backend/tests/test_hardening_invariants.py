"""Architectural invariants for the hardening substrate.

The hardening substrate is observational. The invariants below
guarantee:

* the substrate does not import from any other Operious
  substrate;
* the substrate's runtime does not expose orchestration
  surfaces;
* the substrate does not contain auto-mutation tokens;
* the substrate does not import LLM / network clients.

These tests are the **last line of defence** against semantic
authority contamination.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from app.hardening import HardeningRuntime
from app.hardening.invariants import (
    FORBIDDEN_AUTO_MUTATION_TOKENS,
    PINNED_FINDING_KINDS,
    PINNED_HARDENING_STATUSES,
    PINNED_INTEGRITY_STATUSES,
    PINNED_REPLAY_STATUSES,
    PINNED_SEVERITIES,
    PINNED_SUBSTRATE_NAMES,
    PINNED_SURVIVABILITY_STATUSES,
    PINNED_TRACE_KINDS,
)


HARDENING_ROOT = (
    Path(__file__).parent.parent / "app" / "hardening"
)


_ALLOWED_INTERNAL_PREFIXES = (
    "app.hardening.",
    # Wedge B2 / Branch A: typed identity primitives + the shared
    # AuthorityContext/coexistence helper. Identity is a LEAF
    # substrate (see app/identity/__init__.py); importing from it
    # never introduces a cross-substrate dependency.
    "app.identity",
    # 2.75-\u03b1: capability legality gate (P2-B). The singular
    # cross-substrate legality decision surface; the rest of
    # governance remains opaque to hardening.
    "app.governance.capability",
)

_FORBIDDEN_CROSS_SUBSTRATE_PREFIXES = (
    "app.agents",
    "app.arbitration",
    "app.boundary",
    "app.coordination",
    # `app.governance` is forbidden EXCEPT for the singular
    # `app.governance.capability` gate (2.75-\u03b1 adoption).
    "app.memory",
    "app.organizational_intelligence",
    "app.session",
    "app.supervisor",
    "app.supervision",
    "app.rag",
    "app.embeddings",
    "app.orchestration",
    "app._deprecated",
)
_GOVERNANCE_CAPABILITY_PREFIX = "app.governance.capability"

_FORBIDDEN_NETWORK_LIBS = (
    "openai",
    "anthropic",
    "httpx",
    "requests",
    "aiohttp",
    "boto3",
    "kafka",
)

_PINNED_RUNTIME_METHODS = frozenset(
    {
        "validate_authority_ownership",
        "validate_lineage",
        "validate_replay_equivalence",
        "validate_reconstruction",
        "validate_ordering",
        "detect_contamination",
        "audit_dependencies",
        "validate_survivability",
        "record_failure",
        "classify_containment",
    }
)


@pytest.fixture(scope="module")
def hardening_python_files() -> list[Path]:
    return sorted(HARDENING_ROOT.rglob("*.py"))


def test_hardening_does_not_import_other_substrates(
    hardening_python_files: list[Path],
) -> None:
    offences: list[str] = []
    for path in hardening_python_files:
        for line_no, line in enumerate(
            path.read_text().splitlines(), start=1
        ):
            stripped = line.strip()
            if not (
                stripped.startswith("import ")
                or stripped.startswith("from ")
            ):
                continue
            for forbidden in _FORBIDDEN_CROSS_SUBSTRATE_PREFIXES:
                if (
                    stripped.startswith(f"from {forbidden}")
                    or stripped.startswith(f"import {forbidden}")
                ):
                    offences.append(
                        f"{path.relative_to(HARDENING_ROOT)}:"
                        f"{line_no}: {stripped}"
                    )
            # Governance is forbidden EXCEPT for the singular
            # `app.governance.capability` gate (2.75-\u03b1 adoption).
            if stripped.startswith(
                "from app.governance"
            ) or stripped.startswith("import app.governance"):
                module = (
                    stripped[len("from ") :].split()[0]
                    if stripped.startswith("from ")
                    else stripped[len("import ") :].split()[0]
                )
                if not module.startswith(_GOVERNANCE_CAPABILITY_PREFIX):
                    offences.append(
                        f"{path.relative_to(HARDENING_ROOT)}:"
                        f"{line_no}: {stripped}"
                    )
    assert not offences, "\n".join(offences)


def test_hardening_does_not_import_network_libs(
    hardening_python_files: list[Path],
) -> None:
    offences: list[str] = []
    for path in hardening_python_files:
        for line_no, line in enumerate(
            path.read_text().splitlines(), start=1
        ):
            stripped = line.strip()
            for lib in _FORBIDDEN_NETWORK_LIBS:
                if (
                    stripped.startswith(f"from {lib}")
                    or stripped.startswith(f"import {lib}")
                    or stripped.startswith(
                        f"from {lib}."
                    )
                ):
                    offences.append(
                        f"{path.relative_to(HARDENING_ROOT)}:"
                        f"{line_no}: {stripped}"
                    )
    assert not offences, "\n".join(offences)


def test_hardening_runtime_does_not_expose_orchestration_methods() -> (
    None
):
    public_methods = {
        name
        for name in dir(HardeningRuntime)
        if not name.startswith("_")
    }
    for forbidden in (
        "dispatch",
        "execute",
        "orchestrate",
        "schedule",
        "reroute",
        "retry",
        "auto_recover",
        "auto_heal",
    ):
        assert forbidden not in public_methods


def test_hardening_runtime_method_surface_is_pinned() -> None:
    method_names = {
        name
        for name, _member in inspect.getmembers(
            HardeningRuntime, predicate=inspect.isfunction
        )
        if not name.startswith("_")
        and name not in {"persistence", "runtime_instance_id"}
    }
    assert method_names == _PINNED_RUNTIME_METHODS


def test_hardening_implementation_does_not_use_auto_mutation_tokens(
    hardening_python_files: list[Path],
) -> None:
    """Verify no implementation file uses forbidden auto-mutation tokens.

    The pinned catalogue is defined in `app/hardening/invariants/__init__.py`,
    which is naturally exempt because it stores the catalogue as data.
    """
    offences: list[str] = []
    for path in hardening_python_files:
        if path.parent.name == "invariants":
            continue
        text = path.read_text()
        for token in FORBIDDEN_AUTO_MUTATION_TOKENS:
            if token in text:
                offences.append(
                    f"{path.relative_to(HARDENING_ROOT)}: {token}"
                )
    assert not offences, "\n".join(offences)


def test_pinned_invariant_collections_are_complete() -> None:
    assert "ok" in PINNED_FINDING_KINDS
    assert "critical" in PINNED_SEVERITIES
    assert "validate_lineage" in PINNED_TRACE_KINDS
    assert "governance" in PINNED_SUBSTRATE_NAMES
    assert "passed" in PINNED_INTEGRITY_STATUSES
    assert "byte_identical" in PINNED_REPLAY_STATUSES
    assert "survived" in PINNED_SURVIVABILITY_STATUSES
    assert "completed" in PINNED_HARDENING_STATUSES


def test_allowed_internal_prefixes_only(
    hardening_python_files: list[Path],
) -> None:
    """Hardening code may import its own modules + stdlib. Period."""
    offences: list[str] = []
    for path in hardening_python_files:
        for line_no, line in enumerate(
            path.read_text().splitlines(), start=1
        ):
            stripped = line.strip()
            if not stripped.startswith("from app."):
                continue
            module = stripped[len("from "):].split()[0]
            if not any(
                module.startswith(p)
                for p in _ALLOWED_INTERNAL_PREFIXES
            ):
                offences.append(
                    f"{path.relative_to(HARDENING_ROOT)}:"
                    f"{line_no}: {stripped}"
                )
    assert not offences, "\n".join(offences)

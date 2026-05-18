"""Architectural invariants for the translation substrate."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from app.boundary.translation import (
    TranslationEgressRuntime,
    TranslationIngressRuntime,
)


TRANSLATION_ROOT = (
    Path(__file__).parent.parent
    / "app"
    / "boundary"
    / "translation"
)


# Allowed: own subtree only.
_ALLOWED_INTERNAL_PREFIXES = (
    "app.boundary.translation.",
)

# Forbidden: any other Operious substrate (translation MUST NEVER
# import from cognition, governance, agents, etc.).
_FORBIDDEN_CROSS_SUBSTRATE_PREFIXES = (
    "app.agents",
    "app.arbitration",
    "app.coordination",
    "app.governance",
    "app.hardening",
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

# Translation MUST NOT import LLM / network clients.
_FORBIDDEN_NETWORK_LIBS = (
    "openai",
    "anthropic",
    "httpx",
    "requests",
    "aiohttp",
    "boto3",
    "kafka",
)

_FORBIDDEN_AUTO_MUTATION_TOKENS = (
    "auto_heal",
    "auto_recover",
    "self_modify",
    "auto_route",
    "auto_dispatch",
    "auto_orchestrate",
)

_PINNED_INGRESS_METHODS = frozenset({"translate"})
_PINNED_EGRESS_METHODS = frozenset({"localize"})


@pytest.fixture(scope="module")
def translation_python_files() -> list[Path]:
    return sorted(TRANSLATION_ROOT.rglob("*.py"))


def test_translation_does_not_import_other_substrates(
    translation_python_files: list[Path],
) -> None:
    offences: list[str] = []
    for path in translation_python_files:
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
                if stripped.startswith(
                    f"from {forbidden}"
                ) or stripped.startswith(
                    f"import {forbidden}"
                ):
                    offences.append(
                        f"{path.relative_to(TRANSLATION_ROOT)}:"
                        f"{line_no}: {stripped}"
                    )
    assert not offences, "\n".join(offences)


def test_translation_does_not_import_network_libs(
    translation_python_files: list[Path],
) -> None:
    offences: list[str] = []
    for path in translation_python_files:
        for line_no, line in enumerate(
            path.read_text().splitlines(), start=1
        ):
            stripped = line.strip()
            for lib in _FORBIDDEN_NETWORK_LIBS:
                if stripped.startswith(
                    f"from {lib}"
                ) or stripped.startswith(f"import {lib}"):
                    offences.append(
                        f"{path.relative_to(TRANSLATION_ROOT)}:"
                        f"{line_no}: {stripped}"
                    )
    assert not offences, "\n".join(offences)


def test_translation_does_not_use_auto_mutation_tokens(
    translation_python_files: list[Path],
) -> None:
    offences: list[str] = []
    for path in translation_python_files:
        text = path.read_text()
        for token in _FORBIDDEN_AUTO_MUTATION_TOKENS:
            if token in text:
                offences.append(
                    f"{path.relative_to(TRANSLATION_ROOT)}: {token}"
                )
    assert not offences, "\n".join(offences)


def test_ingress_runtime_method_surface_is_pinned() -> None:
    method_names = {
        name
        for name, _member in inspect.getmembers(
            TranslationIngressRuntime,
            predicate=inspect.isfunction,
        )
        if not name.startswith("_")
    }
    assert method_names == _PINNED_INGRESS_METHODS


def test_egress_runtime_method_surface_is_pinned() -> None:
    method_names = {
        name
        for name, _member in inspect.getmembers(
            TranslationEgressRuntime,
            predicate=inspect.isfunction,
        )
        if not name.startswith("_")
    }
    assert method_names == _PINNED_EGRESS_METHODS


def test_runtimes_do_not_expose_orchestration_methods() -> None:
    for cls in (
        TranslationIngressRuntime,
        TranslationEgressRuntime,
    ):
        public = {
            n for n in dir(cls) if not n.startswith("_")
        }
        for forbidden in (
            "dispatch",
            "execute",
            "orchestrate",
            "schedule",
            "reroute",
            "retry",
        ):
            assert forbidden not in public


def test_allowed_internal_prefixes_only(
    translation_python_files: list[Path],
) -> None:
    offences: list[str] = []
    for path in translation_python_files:
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
                    f"{path.relative_to(TRANSLATION_ROOT)}:"
                    f"{line_no}: {stripped}"
                )
    assert not offences, "\n".join(offences)

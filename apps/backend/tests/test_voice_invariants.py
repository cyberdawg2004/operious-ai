"""Architectural invariants for the voice substrate."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from app.boundary.voice import (
    VoiceEgressRuntime,
    VoiceIngressRuntime,
)


VOICE_ROOT = (
    Path(__file__).parent.parent
    / "app"
    / "boundary"
    / "voice"
)


_ALLOWED_INTERNAL_PREFIXES = (
    "app.boundary.voice.",
    # `app.identity` is the substrate-shareable identity leaf
    # established by Wedge A. It carries the typed identity
    # primitives and the `AuthorityContext` value object that
    # Wedge B2 stamps onto every boundary request contract.
    # It is a LEAF — no sibling-substrate imports — so consuming
    # it does not couple voice to any other substrate.
    "app.identity",
    # `app.core.deterministic_identity` is a substrate-neutral identity
    # primitive used to avoid ambient runtime UUID generation.
    "app.core.deterministic_identity",
    # PR_FIX2: capability gate helpers are shared infrastructure
    # and therefore live under app.core. Governance capability
    # remains narrowly allowed for `OperationalAct` and
    # `GovernanceRuntime`; the rest of governance stays opaque.
    "app.core.capability_gate",
    "app.governance.capability",
    # PR_RT4: durable voice records may use the same narrow Postgres
    # foundation exemption as the apex boundary/session substrates.
    "app.db.base",
    "app.db.repository",
)

_FORBIDDEN_CROSS_SUBSTRATE_PREFIXES = (
    "app.agents",
    "app.arbitration",
    "app.boundary.translation",
    "app.coordination",
    # `app.governance` is forbidden EXCEPT for the singular
    # `app.governance.capability` gate (2.75-\u03b1 adoption).
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

_FORBIDDEN_AUTO_MUTATION_TOKENS = (
    "auto_heal",
    "auto_recover",
    "self_modify",
    "auto_route",
    "auto_dispatch",
    "auto_orchestrate",
)

_PINNED_INGRESS_METHODS = frozenset({"transcribe"})
_PINNED_EGRESS_METHODS = frozenset({"synthesize"})


@pytest.fixture(scope="module")
def voice_python_files() -> list[Path]:
    return sorted(VOICE_ROOT.rglob("*.py"))


def test_voice_does_not_import_other_substrates(
    voice_python_files: list[Path],
) -> None:
    offences: list[str] = []
    for path in voice_python_files:
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
                        f"{path.relative_to(VOICE_ROOT)}:"
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
                        f"{path.relative_to(VOICE_ROOT)}:"
                        f"{line_no}: {stripped}"
                    )
    assert not offences, "\n".join(offences)


def test_voice_does_not_import_network_libs(
    voice_python_files: list[Path],
) -> None:
    offences: list[str] = []
    for path in voice_python_files:
        for line_no, line in enumerate(
            path.read_text().splitlines(), start=1
        ):
            stripped = line.strip()
            for lib in _FORBIDDEN_NETWORK_LIBS:
                if stripped.startswith(
                    f"from {lib}"
                ) or stripped.startswith(f"import {lib}"):
                    offences.append(
                        f"{path.relative_to(VOICE_ROOT)}:"
                        f"{line_no}: {stripped}"
                    )
    assert not offences, "\n".join(offences)


def test_voice_does_not_use_auto_mutation_tokens(
    voice_python_files: list[Path],
) -> None:
    offences: list[str] = []
    for path in voice_python_files:
        text = path.read_text()
        for token in _FORBIDDEN_AUTO_MUTATION_TOKENS:
            if token in text:
                offences.append(
                    f"{path.relative_to(VOICE_ROOT)}: {token}"
                )
    assert not offences, "\n".join(offences)


def test_ingress_runtime_method_surface_is_pinned() -> None:
    method_names = {
        name
        for name, _member in inspect.getmembers(
            VoiceIngressRuntime, predicate=inspect.isfunction
        )
        if not name.startswith("_")
    }
    assert method_names == _PINNED_INGRESS_METHODS


def test_egress_runtime_method_surface_is_pinned() -> None:
    method_names = {
        name
        for name, _member in inspect.getmembers(
            VoiceEgressRuntime, predicate=inspect.isfunction
        )
        if not name.startswith("_")
    }
    assert method_names == _PINNED_EGRESS_METHODS


def test_runtimes_do_not_expose_orchestration_methods() -> None:
    for cls in (VoiceIngressRuntime, VoiceEgressRuntime):
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
    voice_python_files: list[Path],
) -> None:
    offences: list[str] = []
    for path in voice_python_files:
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
                    f"{path.relative_to(VOICE_ROOT)}:"
                    f"{line_no}: {stripped}"
                )
    assert not offences, "\n".join(offences)

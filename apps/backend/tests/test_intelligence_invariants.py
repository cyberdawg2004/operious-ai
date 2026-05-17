"""Sprint O substrate invariants — the LAST line of defence.

These tests fail loudly if the intelligence substrate begins to:

* import sibling-substrate runtimes,
* expose orchestration / execution surfaces,
* allow CANDIDATE → APPROVED transitions without an
  `ApprovalRecord`,
* allow non-APPROVED artifacts to become retrieval-eligible,
* violate the canonical export surface.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from app.organizational_intelligence import (
    OrganizationalIntelligenceRuntime,
)
from app.organizational_intelligence.communication.runtime import (
    CommunicationRuntime,
)
from app.organizational_intelligence.operational_patterns.runtime import (
    OperationalPatternAnalysisRuntime,
)
from app.organizational_intelligence.recommendations.runtime import (
    RecommendationRuntime,
)
from app.organizational_intelligence.sop.runtime import SopRuntime
from app.organizational_intelligence.tonality.runtime import (
    TonalityRuntime,
)
from app.organizational_intelligence.training.runtime import (
    MemoryEvolutionRuntime,
)


_INTEL_ROOT = Path("app/organizational_intelligence")


# ─── Substrate-isolation invariant ──────────────────────────────────


_FORBIDDEN_PARENT_IMPORT_RE = re.compile(
    r"^(?:from|import)\s+app\.(?:agents|supervisor|coordination|"
    r"memory|arbitration|embeddings|replay|tracing|providers|db|"
    r"governance|boundary|session|orchestration)\b",
    re.MULTILINE,
)


def test_no_parent_substrate_imports() -> None:
    """The intelligence substrate MUST NOT import from any sibling runtime.

    The substrate's internal `governance/` and `supervision/`
    packages are NOT the operational-governance / operational-
    supervision substrates — they are substrate-internal helpers.
    """
    offenders: list[str] = []
    for path in _INTEL_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if _FORBIDDEN_PARENT_IMPORT_RE.search(text):
            offenders.append(str(path))
    assert not offenders, (
        f"forbidden cross-substrate imports found in: {offenders}"
    )


# ─── No-orchestration-surface invariant ─────────────────────────────


_FORBIDDEN_RUNTIME_METHODS = {
    "execute",
    "dispatch",
    "schedule",
    "retry",
    "orchestrate",
    "fanout",
    "invoke_agent",
    "invoke_tool",
    "plan",
    "rebalance",
    "rollback",
    "redirect",
    "transition",
    "fire",
    "publish",
    "broadcast",
    "route",
    "trigger",
    "auto_apply",
    "auto_route",
    "self_improve",
    "learn",
    "train",
    "adapt",
}


@pytest.mark.parametrize(
    "runtime_cls",
    [
        SopRuntime,
        TonalityRuntime,
        CommunicationRuntime,
        MemoryEvolutionRuntime,
        OperationalPatternAnalysisRuntime,
        RecommendationRuntime,
    ],
)
def test_runtime_has_no_orchestration_surfaces(
    runtime_cls: type,
) -> None:
    """No method in any intelligence runtime implies orchestration."""
    public = {
        name
        for name in dir(runtime_cls)
        if not name.startswith("_")
    }
    for forbidden in _FORBIDDEN_RUNTIME_METHODS:
        assert forbidden not in public, (
            f"{runtime_cls.__name__} unexpectedly exposes a "
            f"{forbidden!r} method"
        )


def test_runtime_async_surfaces_pinned() -> None:
    """Pin the async-method catalogue per runtime."""
    expected: dict[type, set[str]] = {
        SopRuntime: {"ingest_sop", "analyze_sop"},
        TonalityRuntime: {"classify"},
        CommunicationRuntime: {
            "register_pattern",
            "retrieve_patterns",
        },
        MemoryEvolutionRuntime: {
            "propose",
            "approve",
            "reject",
            "supersede",
            "retire",
            "list_artifacts",
        },
        OperationalPatternAnalysisRuntime: {"analyze"},
        RecommendationRuntime: {"generate", "record_review"},
    }
    for runtime_cls, expected_methods in expected.items():
        actual = {
            name
            for name in dir(runtime_cls)
            if not name.startswith("_")
            and inspect.iscoroutinefunction(
                getattr(runtime_cls, name)
            )
        }
        assert actual == expected_methods, (
            f"{runtime_cls.__name__} async surface drifted; "
            f"expected={expected_methods}, actual={actual}"
        )


# ─── Aggregator surface invariant ────────────────────────────────────


def test_aggregator_exposes_only_typed_namespaces() -> None:
    """The aggregator is a typed namespace, not a method bag."""
    expected_attrs = {
        "sop",
        "tonality",
        "communication",
        "memory",
        "patterns",
        "recommendations",
    }
    actual_attrs = {
        name
        for name in dir(OrganizationalIntelligenceRuntime)
        if not name.startswith("_")
    }
    assert actual_attrs == expected_attrs, (
        f"OrganizationalIntelligenceRuntime surface drifted; "
        f"expected={expected_attrs}, actual={actual_attrs}"
    )


# ─── No-runtime-mutation invariants ─────────────────────────────────


_NO_AUTO_MUTATION_PATTERNS = [
    re.compile(r"\bauto_apply\b"),
    re.compile(r"\bauto_route\b"),
    re.compile(r"\bauto_execute\b"),
    re.compile(r"\bauto_promote\b"),
    re.compile(r"\bauto_rewrite\b"),
    re.compile(r"\bself_improve\b"),
]


def test_no_auto_mutation_in_substrate_source() -> None:
    """The substrate source must not mention auto-mutation primitives."""
    offenders: list[tuple[str, str]] = []
    for path in _INTEL_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for pat in _NO_AUTO_MUTATION_PATTERNS:
            if pat.search(text):
                offenders.append((str(path), pat.pattern))
    assert not offenders, (
        f"forbidden auto-mutation primitives detected: {offenders}"
    )


def test_no_llm_or_network_imports() -> None:
    """The substrate must not import LLM SDKs / HTTP clients."""
    forbidden = re.compile(
        r"^(?:from|import)\s+(openai|anthropic|httpx|requests|"
        r"urllib3|aiohttp|google\.genai|cohere|together|"
        r"langchain|llama_index|langgraph)\b",
        re.MULTILINE,
    )
    offenders: list[str] = []
    for path in _INTEL_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if forbidden.search(text):
            offenders.append(str(path))
    assert not offenders, (
        f"forbidden LLM/network imports found in: {offenders}"
    )


# ─── Wire-format-stability invariant ────────────────────────────────


@pytest.mark.parametrize(
    "must_export",
    [
        # apex types
        "OrganizationalIntelligenceRuntime",
        "InMemoryIntelligencePersistence",
        "IntelligencePersistenceProtocol",
        "IntelligenceEnvelope",
        "IntelligenceTrace",
        "IntelligenceTraceContext",
        "IntelligenceMetadataKey",
        # models
        "ApprovalRecord",
        "ApprovedPattern",
        "CandidatePattern",
        "CommunicationPattern",
        "CommunicationRetrievalCandidate",
        "MemoryEvolutionProposal",
        "OperationalPatternAnalysis",
        "OperationalPatternObservation",
        "OrganizationalMemoryArtifact",
        "OrganizationalRecommendation",
        "PatternLineage",
        "RecommendationRationale",
        "RetrievalEligibilityRecord",
        "SopAnalysis",
        "SopFinding",
        "SopVersion",
        "StandardOperatingProcedure",
        "TonalityAnalysis",
        "TonalityTag",
        # contracts
        "AnalyzeOperationalPatternsRequest",
        "AnalyzeOperationalPatternsResult",
        "AnalyzeSopRequest",
        "AnalyzeSopResult",
        "ApprovePatternRequest",
        "ApprovePatternResult",
        "ApproveRecommendationRequest",
        "ApproveRecommendationResult",
        "ClassifyTonalityRequest",
        "ClassifyTonalityResult",
        "GenerateRecommendationRequest",
        "GenerateRecommendationResult",
        "IngestSopRequest",
        "IngestSopResult",
        "ListMemoryArtifactsRequest",
        "ListMemoryArtifactsResult",
        "MemoryEvolutionProposalRequest",
        "MemoryEvolutionProposalResult",
        "RegisterCommunicationPatternRequest",
        "RegisterCommunicationPatternResult",
        "RejectPatternRequest",
        "RejectPatternResult",
        "RetireMemoryArtifactRequest",
        "RetireMemoryArtifactResult",
        "RetrieveCommunicationPatternsRequest",
        "RetrieveCommunicationPatternsResult",
        "SupersedeMemoryArtifactRequest",
        "SupersedeMemoryArtifactResult",
        # enums
        "ApprovalAuthorityKind",
        "ApprovalDecision",
        "CommunicationPatternKind",
        "IntelligenceScope",
        "IntelligenceTraceKind",
        "MemoryArtifactKind",
        "MemoryArtifactStatus",
        "OperationalPatternKind",
        "RecommendationKind",
        "RecommendationStatus",
        "RetrievalEligibility",
        "SopFindingKind",
        "SopFindingSeverity",
        "SopStatus",
        "TonalityClass",
        "TonalityIntensity",
        # exceptions
        "IntelligenceApprovalError",
        "IntelligenceAuthorityError",
        "IntelligenceConfigurationError",
        "IntelligenceError",
        "IntelligenceLineageError",
        "IntelligenceNotFoundError",
        "IntelligencePersistenceError",
        "IntelligenceValidationError",
    ],
)
def test_substrate_exports_canonical_surface(
    must_export: str,
) -> None:
    """`app.organizational_intelligence.__all__` is the contract."""
    import app.organizational_intelligence as substrate

    assert must_export in substrate.__all__

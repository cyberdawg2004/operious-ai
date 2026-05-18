"""Boundary substrate invariants — Sprint M containment.

These tests are the LAST line of defence against semantic drift.
They MUST stay green; a failure here means the boundary substrate
has begun to absorb orchestration / execution / sibling-substrate
semantics.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from app.boundary import (
    BoundaryEgressRuntime,
    BoundaryIngressRuntime,
)
from app.boundary.adapters.base import (
    BaseEgressAdapter,
    BaseIngressAdapter,
)
from app.boundary.idempotency.detector import (
    BoundaryReplayDetector,
)
from app.boundary.idempotency.registry import (
    BoundaryIdempotencyRegistry,
)
from app.boundary.normalization.normalizer import (
    BoundaryNormalizer,
)
from app.boundary.registry.registry import (
    BoundaryAdapterRegistry,
)


_BOUNDARY_ROOT = Path("app/boundary")


# ─── Substrate-isolation invariant ──────────────────────────────────


_FORBIDDEN_PARENT_IMPORT_RE = re.compile(
    r"^(?:from|import)\s+app\.(?:agents|supervisor|coordination|"
    r"memory|arbitration|embeddings|replay|tracing|providers|db|"
    r"governance)\b",
    re.MULTILINE,
)


def test_no_parent_substrate_imports() -> None:
    """The boundary substrate MUST NOT import from any sibling runtime."""
    offenders: list[str] = []
    for path in _BOUNDARY_ROOT.rglob("*.py"):
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
}


@pytest.mark.parametrize(
    "runtime_cls",
    [
        BoundaryIngressRuntime,
        BoundaryEgressRuntime,
    ],
)
def test_runtime_has_no_orchestration_surfaces(runtime_cls: type) -> None:
    """No methods that imply orchestration / execution authority."""
    public = {
        name
        for name in dir(runtime_cls)
        if not name.startswith("_")
        and callable(getattr(runtime_cls, name, None))
    }
    for forbidden in _FORBIDDEN_RUNTIME_METHODS:
        assert forbidden not in public, (
            f"{runtime_cls.__name__} unexpectedly exposes a "
            f"{forbidden!r} method"
        )


def test_ingress_runtime_only_exposes_ingest() -> None:
    """The async surface is exactly `ingest` — no execute/dispatch/retry."""
    async_methods = {
        name
        for name in dir(BoundaryIngressRuntime)
        if not name.startswith("_")
        and inspect.iscoroutinefunction(
            getattr(BoundaryIngressRuntime, name)
        )
    }
    assert async_methods == {"ingest"}


def test_egress_runtime_only_exposes_emit() -> None:
    async_methods = {
        name
        for name in dir(BoundaryEgressRuntime)
        if not name.startswith("_")
        and inspect.iscoroutinefunction(
            getattr(BoundaryEgressRuntime, name)
        )
    }
    assert async_methods == {"emit"}


# ─── Adapter-discipline invariant ───────────────────────────────────


def test_base_ingress_adapter_only_exposes_normalize() -> None:
    abstracts = {
        name
        for name, member in inspect.getmembers(
            BaseIngressAdapter, inspect.isfunction
        )
        if getattr(member, "__isabstractmethod__", False)
    }
    assert abstracts == {"normalize"}


def test_base_egress_adapter_only_exposes_serialize() -> None:
    abstracts = {
        name
        for name, member in inspect.getmembers(
            BaseEgressAdapter, inspect.isfunction
        )
        if getattr(member, "__isabstractmethod__", False)
    }
    assert abstracts == {"serialize"}


# ─── Wire-format-stability invariant ────────────────────────────────


def test_substrate_exports_canonical_surface() -> None:
    """`app.boundary.__all__` is the substrate's external contract."""
    import app.boundary as substrate

    must_export = {
        # Enums
        "BoundaryDirection",
        "BoundarySourceType",
        "BoundaryMessageType",
        "BoundaryNormalizationStatus",
        "BoundaryReplayDisposition",
        # Identity
        "BoundaryEventId",
        "BoundaryIngressId",
        "BoundaryEgressId",
        "ExternalMessageId",
        "ExternalConversationId",
        "derive_event_id",
        "derive_replay_key",
        # Models
        "ExternalBoundaryEvent",
        "BoundaryNormalizationResult",
        "BoundaryReplayRecord",
        "BoundarySource",
        "IngressPayload",
        "EgressPayload",
        # Contracts
        "BoundaryIngressRequest",
        "BoundaryIngressResult",
        "BoundaryEgressRequest",
        "BoundaryEgressResult",
        # Envelope + tracing
        "BoundaryIngressEnvelope",
        "BoundaryEgressEnvelope",
        "BoundaryTrace",
        "BoundaryTraceContext",
        # Adapters
        "BaseIngressAdapter",
        "BaseEgressAdapter",
        "ZendeskWebhookAdapter",
        "WhatsAppWebhookAdapter",
        "TwilioVoiceAdapter",
        # Idempotency
        "BoundaryIdempotencyRegistry",
        "BoundaryReplayDecision",
        "BoundaryReplayDetector",
        # Normalisation
        "BoundaryNormalizer",
        "canonicalize_payload",
        "canonicalize_metadata",
        "content_fingerprint",
        # Persistence
        "BoundaryIngressRecord",
        "BoundaryEgressRecord",
        "BoundaryPersistenceProtocol",
        "InMemoryBoundaryPersistence",
        # Registry
        "BoundaryAdapterRegistry",
        # Runtimes
        "BoundaryIngressRuntime",
        "BoundaryEgressRuntime",
    }
    exported = set(substrate.__all__)
    missing = must_export - exported
    assert not missing, f"missing canonical exports: {missing}"


# ─── Replay-equivalence smoke (ties enums + identity together) ──────


def test_all_replay_dispositions_are_distinct_strings() -> None:
    from app.boundary.enums import BoundaryReplayDisposition

    values = [d.value for d in BoundaryReplayDisposition]
    assert len(set(values)) == len(values)


# ─── Composition smoke ──────────────────────────────────────────────


def test_runtime_composition_is_valid() -> None:
    reg = BoundaryAdapterRegistry()
    idem = BoundaryIdempotencyRegistry()
    ing = BoundaryIngressRuntime(
        adapters=reg,
        idempotency=idem,
        normalizer=BoundaryNormalizer(),
        detector=BoundaryReplayDetector(),
    )
    eg = BoundaryEgressRuntime(adapters=reg)
    assert ing.runtime_instance_id != eg.runtime_instance_id

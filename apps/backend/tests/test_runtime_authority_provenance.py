# pyright: reportArgumentType=false, reportAttributeAccessIssue=false
"""P2-C regression tests — emitted traces carry tenant_authority_source.

P2-A established that orchestration runtimes consume ``AuthorityContext``
via ``request_authority_resolution`` to compute a singular
``AuthorityResolution.tenant_id``. P2-C closes the audit loop: every
runtime that emits a trace must also stamp ``resolution.source.value``
onto the trace so audit/replay consumers can reconstruct **which**
authority surface (typed / legacy / observed / anonymous) won.

Already covered by prior wedges:
* SupervisorTrace.tenant_authority_source — B6
* CoordinationTrace.tenant_authority_source — B7
* CoordinationEnvelope.tenant_authority_source — B7
* CoordinationRecord.tenant_authority_source — B7

P2-C adds the field + propagation to the remaining trace surfaces.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.identity import (
    AuthorityContext,
    AuthoritySource,
)


_TENANT = "acme-prov"


# ─── arbitration trace ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_arbitration_trace_carries_authority_source() -> None:
    from app.arbitration.contracts.requests import ArbitrationRequest
    from app.arbitration.evaluators.base import (
        ArbitrationEvaluatorOutput,
        BaseArbitrationEvaluator,
    )
    from app.arbitration.models.case import ArbitrationCase
    from app.arbitration.registry.registry import (
        ArbitrationEvaluatorRegistry,
    )
    from app.arbitration.runtime.runtime import (
        OperationalArbitrationRuntime,
    )

    class _Noop(BaseArbitrationEvaluator):
        def evaluate(
            self, request, *, evaluation_id
        ) -> ArbitrationEvaluatorOutput:
            return ArbitrationEvaluatorOutput(
                findings=(), conflicts=(), deadlock_witnesses=()
            )

    runtime = OperationalArbitrationRuntime(
        registry=ArbitrationEvaluatorRegistry(
            evaluators=(_Noop(name="noop"),)
        )
    )
    envelope = await runtime.evaluate(
        ArbitrationRequest(
            case=ArbitrationCase(case_id="case-1"),
            authority=AuthorityContext(tenant_id=_TENANT),
        )
    )

    assert envelope.trace.tenant_id == _TENANT
    assert (
        envelope.trace.tenant_authority_source
        == AuthoritySource.TYPED_AUTHORITY.value
    )


# ─── session trace ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_session_trace_carries_authority_source() -> None:
    from app.session.contracts.requests import OpenSessionRequest
    from app.session.enums import SessionScope
    from app.session.persistence.memory import (
        InMemorySessionPersistence,
    )
    from app.session.runtime.runtime import SessionRuntime

    runtime = SessionRuntime(persistence=InMemorySessionPersistence())
    envelope = await runtime.open_session(
        OpenSessionRequest(
            scope=SessionScope.TENANT,
            external_handle="handle-1",
            authority=AuthorityContext(tenant_id=_TENANT),
        )
    )

    assert envelope.trace.tenant_id == _TENANT
    assert (
        envelope.trace.tenant_authority_source
        == AuthoritySource.TYPED_AUTHORITY.value
    )


# ─── OI sop / tonality traces ───────────────────────────────────────


@pytest.mark.asyncio
async def test_sop_trace_carries_authority_source() -> None:
    from app.organizational_intelligence.contracts.requests import (
        IngestSopRequest,
    )
    from app.organizational_intelligence.persistence.memory import (
        InMemoryIntelligencePersistence,
    )
    from app.organizational_intelligence.sop.runtime import SopRuntime

    runtime = SopRuntime(persistence=InMemoryIntelligencePersistence())
    envelope = await runtime.ingest_sop(
        IngestSopRequest(
            external_handle="sop-handle-2",
            title="Greet",
            body="Greet politely on answer.",
            authority=AuthorityContext(tenant_id=_TENANT),
        )
    )

    assert envelope.trace.tenant_id == _TENANT
    assert (
        envelope.trace.tenant_authority_source
        == AuthoritySource.TYPED_AUTHORITY.value
    )


@pytest.mark.asyncio
async def test_tonality_trace_carries_authority_source() -> None:
    from app.organizational_intelligence.contracts.requests import (
        ClassifyTonalityRequest,
    )
    from app.organizational_intelligence.persistence.memory import (
        InMemoryIntelligencePersistence,
    )
    from app.organizational_intelligence.tonality.runtime import (
        TonalityRuntime,
    )

    runtime = TonalityRuntime(
        persistence=InMemoryIntelligencePersistence()
    )
    envelope = await runtime.classify(
        ClassifyTonalityRequest(
            content="Hello, how can I help?",
            authority=AuthorityContext(tenant_id=_TENANT),
        )
    )

    assert envelope.trace.tenant_id == _TENANT
    assert (
        envelope.trace.tenant_authority_source
        == AuthoritySource.TYPED_AUTHORITY.value
    )


# ─── invariant: every migrated trace carries the field ──────────────


def test_every_trace_declares_tenant_authority_source_field() -> None:
    """P2-C invariant: every trace dataclass touched by P2-A/P2-C must
    declare the ``tenant_authority_source: str | None`` field.

    Static source scan keeps the substrate boundary intact without
    needing per-substrate import.
    """
    trace_files = (
        "app/arbitration/tracing.py",
        "app/session/traces/trace.py",
        "app/boundary/translation/traces/trace.py",
        "app/boundary/voice/traces/trace.py",
        "app/hardening/traces/trace.py",
        "app/coordination/policy/tracing.py",
        "app/coordination/topology/tracing.py",
        "app/organizational_intelligence/traces/trace.py",
        # B6/B7 (already had it pre-P2-C, but pin here for completeness)
        "app/supervisor/tracing.py",
        "app/coordination/tracing.py",
    )
    repo_root = Path(__file__).resolve().parents[1]
    for relpath in trace_files:
        src = (repo_root / relpath).read_text(encoding="utf-8")
        if "tenant_authority_source: str | None" not in src:
            pytest.fail(
                f"trace {relpath} lacks tenant_authority_source field"
            )


def test_every_runtime_emits_authority_source() -> None:
    """P2-C invariant: every orchestration runtime that adopts the
    P2-A resolver must also stamp the source onto its emitted trace
    (i.e., reference ``resolution.source.value`` somewhere).
    """
    runtime_files = (
        "app/arbitration/runtime/runtime.py",
        "app/session/runtime/runtime.py",
        "app/coordination/policy/runtime/runtime.py",
        "app/coordination/topology/runtime/runtime.py",
        "app/boundary/translation/ingress/runtime.py",
        "app/boundary/translation/egress/runtime.py",
        "app/boundary/voice/ingress/runtime.py",
        "app/boundary/voice/egress/runtime.py",
        "app/hardening/validation/runtime.py",
        "app/organizational_intelligence/sop/runtime.py",
        "app/organizational_intelligence/tonality/runtime.py",
        "app/organizational_intelligence/communication/runtime.py",
        "app/organizational_intelligence/recommendations/runtime.py",
        "app/organizational_intelligence/training/runtime.py",
    )
    repo_root = Path(__file__).resolve().parents[1]
    for relpath in runtime_files:
        src = (repo_root / relpath).read_text(encoding="utf-8")
        # Hardening uses request_authority_resolution inside the
        # envelope/fail helpers (contract-agnostic via getattr); the
        # other runtimes pass resolution.source.value explicitly.
        if (
            "resolution.source.value" in src
            or "request_authority_resolution(request)" in src
        ):
            continue
        pytest.fail(
            f"runtime {relpath} does not stamp authority source onto "
            "its emitted trace"
        )

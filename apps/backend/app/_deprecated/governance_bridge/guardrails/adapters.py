"""Governed context-assembly runtime.

The shipping Sprint I integration. Composes:

* `GovernanceRuntime` — the substrate apex.
* `ContextAssemblyService` (Sprint H) — left exactly as-is.

The composition runs governance at TWO stages:

1. **PRE_RETRIEVAL** — gate the request before any work happens.
   Subject is `{"query": ..., "policy_id": ..., "tenant_id": ...}`.
   Blocking decisions (DENY / REQUIRE_APPROVAL / ESCALATE) abort
   without invoking Sprint H. REDACT / DEGRADE at this stage attach
   `RuntimeRestriction`s for inspection but do not modify the request
   (Sprint I foundations does not implement REDACT mutation here —
   that lands when the assembly service exposes per-stage hooks).

2. **PRE_EXECUTION** — gate the assembled context BEFORE downstream
   consumers (a future AI call, an agent action, an export) use it.
   Subject is `{"context_summary": {...}}`. Same blocking semantics.

If governance is *not* configured for a stage, the runtime skips it
silently — the chain registry being empty for that stage is a valid
operational state (e.g., dev environments).

What it returns:

`GovernedAssemblyEnvelope` carrying:

* `assembled_context`     — present iff Sprint H + both governance
                            stages permitted execution,
* `pre_retrieval_envelope` — the PRE_RETRIEVAL governance envelope,
                              always populated when configured,
* `context_envelope`       — Sprint H's `ContextEnvelope`, populated
                              when retrieval was permitted,
* `pre_execution_envelope` — the PRE_EXECUTION governance envelope,
                              populated when assembly succeeded.

This shape mirrors Sprint H's `ContextEnvelope.retrieval_envelope` /
`reranking_envelope` pattern: sub-envelopes preserved for full replay
even when the top-level envelope failed.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from app.governance.context import GovernanceContext
from app.governance.decisions import GovernanceDecision
from app.governance.enforcement.runtime import GovernanceRuntime
from app.governance.envelopes import GovernanceEnvelope
from app.governance.enums import Decision, EnforcementStage
from app.governance.identity.correlation import CorrelationContext
from app._deprecated.governance_bridge.subjects_factories import (
    execution_subject_for_assembled_context,
    retrieval_subject_for_assembly,
)
from app.observability.context import get_request_id
from app._deprecated.rag.assembly.envelopes import ContextEnvelope
from app._deprecated.rag.assembly.models import AssembledContext, AssemblyRequest
from app._deprecated.rag.assembly.service import ContextAssemblyService


@dataclass(frozen=True, slots=True)
class GovernedAssemblyRequest:
    """Wraps an `AssemblyRequest` with governance metadata.

    The `tenant_id` and `actor` propagate into the governance contexts
    constructed at each stage. `assembly` is the Sprint H request,
    handed verbatim to `ContextAssemblyService.assemble()` if governance
    permits.
    """

    assembly: AssemblyRequest
    tenant_id: str | None = None
    actor: str = "system"
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])


@dataclass(frozen=True, slots=True)
class GovernedAssembledContext:
    """The successful payload of a governed assembly call.

    Carries the underlying Sprint H `AssembledContext` plus the
    `GovernanceDecision` artefacts so callers see *both* the
    retrieval / grounding output AND every restriction that downstream
    consumers must honour.
    """

    context: AssembledContext
    pre_retrieval_decision: GovernanceDecision
    pre_execution_decision: GovernanceDecision

    @property
    def restrictions(self) -> tuple:
        """Aggregated restrictions across both governance stages."""
        return (
            *self.pre_retrieval_decision.restrictions,
            *self.pre_execution_decision.restrictions,
        )


@dataclass(frozen=True, slots=True)
class GovernedAssemblyEnvelope:
    """Never-raising container around a governed assembly outcome.

    Sub-envelopes preserved regardless of overall success so replayers
    can read partial lineage on failure.
    """

    result: GovernedAssembledContext | None = None
    error: BaseException | None = None
    failed_stage: str | None = None
    pre_retrieval_envelope: GovernanceEnvelope | None = None
    context_envelope: ContextEnvelope | None = None
    pre_execution_envelope: GovernanceEnvelope | None = None
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])

    @property
    def is_ok(self) -> bool:
        return self.error is None and self.result is not None

    def unwrap(self) -> GovernedAssembledContext:
        if not self.is_ok:
            raise RuntimeError(
                "GovernedAssemblyEnvelope.unwrap() called on a failed "
                "envelope; inspect .failed_stage, .error, and the "
                "sub-envelopes first."
            ) from self.error
        assert self.result is not None
        return self.result


class GovernedAssemblyRuntime:
    """Compose `GovernanceRuntime` + `ContextAssemblyService` cleanly.

    The two services own their respective concerns; this composition
    is the *coordinator* that runs them in order and threads the
    request id / metadata through the trace chain.
    """

    PRE_RETRIEVAL_ACTION = "rag.assemble_context.pre_retrieval"
    PRE_EXECUTION_ACTION = "rag.assemble_context.pre_execution"

    def __init__(
        self,
        *,
        governance_runtime: GovernanceRuntime,
        assembly_service: ContextAssemblyService,
    ) -> None:
        self._governance = governance_runtime
        self._assembly = assembly_service

    async def assemble(
        self,
        request: GovernedAssemblyRequest,
        *,
        request_id: str | None = None,
        correlation: CorrelationContext | None = None,
    ) -> GovernedAssemblyEnvelope:
        """Run governed assembly. Never raises.

        Args:
            request:       Governed assembly input.
            request_id:    Platform-wide request id; sourced from the
                           observability context when omitted.
            correlation:   Optional pre-built correlation context. When
                           omitted, the runtime constructs one (fresh
                           UUID4) — the resulting `correlation_id` is
                           threaded through both governance evaluations
                           so persistence queries can retrieve them
                           together. Callers running multiple
                           pipelines under one logical operation
                           pass an explicit `CorrelationContext`.
        """
        rid = request_id or get_request_id()
        resource = (
            f"tenant:{request.tenant_id or 'global'}/"
            f"action:rag.assemble_context"
        )

        if correlation is None:
            correlation = CorrelationContext(
                correlation_id=uuid.uuid4(),
                request_id=rid,
            )

        # ─── 1. PRE_RETRIEVAL governance ─────────────────────────────
        pre_retrieval_env: GovernanceEnvelope | None = None
        if self._governance.chain_for(EnforcementStage.PRE_RETRIEVAL) is not None:
            pre_retrieval_env = await self._governance.evaluate(
                GovernanceContext(
                    stage=EnforcementStage.PRE_RETRIEVAL,
                    action=self.PRE_RETRIEVAL_ACTION,
                    resource=resource,
                    actor=request.actor,
                    tenant_id=request.tenant_id,
                    request_id=rid,
                    subject=retrieval_subject_for_assembly(
                        request=request.assembly,
                        tenant_id=request.tenant_id,
                        request_id=rid,
                        metadata=request.metadata,
                    ),
                    correlation_id=correlation.correlation_id,
                    metadata=dict(request.metadata),
                )
            )
            if not pre_retrieval_env.is_ok:
                # Governance evaluation itself failed — surface the
                # error verbatim. This is distinct from a successful
                # evaluation that produced a DENY.
                return GovernedAssemblyEnvelope(
                    error=pre_retrieval_env.error,
                    failed_stage="governance.pre_retrieval",
                    pre_retrieval_envelope=pre_retrieval_env,
                    metadata=dict(request.metadata),
                )
            pre_retrieval_decision = pre_retrieval_env.unwrap()
            if pre_retrieval_decision.is_blocking:
                return GovernedAssemblyEnvelope(
                    error=_blocking_error(pre_retrieval_decision),
                    failed_stage="governance.pre_retrieval",
                    pre_retrieval_envelope=pre_retrieval_env,
                    metadata=dict(request.metadata),
                )
        else:
            # No chain configured for PRE_RETRIEVAL: substrate skips,
            # operationally equivalent to ALLOW. The envelope chain
            # captures the absence by leaving `pre_retrieval_envelope`
            # None — replayers see the no-chain state explicitly.
            pre_retrieval_decision = _synthesise_allow(
                stage=EnforcementStage.PRE_RETRIEVAL
            )

        # ─── 2. Sprint H assembly ────────────────────────────────────
        context_env = await self._assembly.assemble(
            request.assembly,
            request_id=rid,
        )
        if not context_env.is_ok or context_env.result is None:
            return GovernedAssemblyEnvelope(
                error=context_env.error or RuntimeError(
                    f"context assembly failed at "
                    f"{context_env.trace.failed_stage or 'unknown'}"
                ),
                failed_stage=(
                    f"assembly.{context_env.trace.failed_stage or 'unknown'}"
                ),
                pre_retrieval_envelope=pre_retrieval_env,
                context_envelope=context_env,
                metadata=dict(request.metadata),
            )
        assembled = context_env.result

        # ─── 3. PRE_EXECUTION governance ─────────────────────────────
        pre_execution_env: GovernanceEnvelope | None = None
        if self._governance.chain_for(EnforcementStage.PRE_EXECUTION) is not None:
            pre_execution_env = await self._governance.evaluate(
                GovernanceContext(
                    stage=EnforcementStage.PRE_EXECUTION,
                    action=self.PRE_EXECUTION_ACTION,
                    resource=resource,
                    actor=request.actor,
                    tenant_id=request.tenant_id,
                    request_id=rid,
                    subject=execution_subject_for_assembled_context(
                        context=assembled,
                        tenant_id=request.tenant_id,
                        request_id=rid,
                        execution_action=self.PRE_EXECUTION_ACTION,
                        metadata=request.metadata,
                    ),
                    correlation_id=correlation.correlation_id,
                    metadata=dict(request.metadata),
                )
            )
            if not pre_execution_env.is_ok:
                return GovernedAssemblyEnvelope(
                    error=pre_execution_env.error,
                    failed_stage="governance.pre_execution",
                    pre_retrieval_envelope=pre_retrieval_env,
                    context_envelope=context_env,
                    pre_execution_envelope=pre_execution_env,
                    metadata=dict(request.metadata),
                )
            pre_execution_decision = pre_execution_env.unwrap()
            if pre_execution_decision.is_blocking:
                return GovernedAssemblyEnvelope(
                    error=_blocking_error(pre_execution_decision),
                    failed_stage="governance.pre_execution",
                    pre_retrieval_envelope=pre_retrieval_env,
                    context_envelope=context_env,
                    pre_execution_envelope=pre_execution_env,
                    metadata=dict(request.metadata),
                )
        else:
            pre_execution_decision = _synthesise_allow(
                stage=EnforcementStage.PRE_EXECUTION
            )

        # ─── 4. Successful governed assembly ─────────────────────────
        return GovernedAssemblyEnvelope(
            result=GovernedAssembledContext(
                context=assembled,
                pre_retrieval_decision=pre_retrieval_decision,
                pre_execution_decision=pre_execution_decision,
            ),
            pre_retrieval_envelope=pre_retrieval_env,
            context_envelope=context_env,
            pre_execution_envelope=pre_execution_env,
            metadata=dict(request.metadata),
        )


# ─── Helpers ──────────────────────────────────────────────────────────


def _blocking_error(decision: GovernanceDecision):
    """Wrap a blocking decision in `GovernanceViolationError`.

    Imported locally so the guardrail file's top-level imports stay
    confined to public substrate surfaces.
    """
    from app.governance.exceptions import GovernanceViolationError

    return GovernanceViolationError(
        f"governance blocked execution at {decision.stage.value}: "
        f"{decision.reason}",
        decision=decision,
    )


def _synthesise_allow(*, stage: EnforcementStage) -> GovernanceDecision:
    """Build an ALLOW decision used when no chain is configured.

    Operationally equivalent to "no governance configured for this
    stage" — the substrate skips, but downstream code still receives a
    well-typed `GovernanceDecision` to attach to its own audit record.
    """
    import uuid
    from datetime import datetime, timezone

    return GovernanceDecision(
        decision_id=uuid.uuid4(),
        decision=Decision.ALLOW,
        stage=stage,
        policy_chain_id="<no-chain-configured>",
        evaluated_rules=(),
        violations=(),
        restrictions=(),
        reason="no governance chain configured for this stage",
        decided_at=datetime.now(timezone.utc),
        metadata={"synthesised": True},
    )


__all__ = [
    "GovernedAssembledContext",
    "GovernedAssemblyEnvelope",
    "GovernedAssemblyRequest",
    "GovernedAssemblyRuntime",
]

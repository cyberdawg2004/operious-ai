"""Governance runtime — apex orchestrator.

One public method (`evaluate`) runs the full pipeline:

    GovernanceContext  →  PolicyChain (engine)
                       →  build_decision (pure aggregation)
                       →  EnforcementHandler (action)
                       →  GovernanceEnvelope

The runtime is the **single** producer of `GovernanceEnvelope`. It is
the only place that:

* selects the chain for a given stage (via the chain registry),
* dispatches the right handler (via the handler registry),
* emits logs / metrics / audit events,
* attributes failure to a specific pipeline stage.

The runtime never raises — every failure mode produces an envelope:

* engine failure  → policy synthesised a DENY; envelope is_ok=True
                    (the runtime succeeded; the *verdict* is DENY).
* handler failure → envelope is_ok=False with error attached.
* config failure  → envelope is_ok=False with the configuration error.

Why this matters for replay: a saved envelope is sufficient to
reconstruct the exact decision lineage (every policy invocation,
every rule, the aggregation outcome, the handler's structured
action). Combined with a deterministic policy implementation, the
substrate is bit-for-bit replayable.
"""

from __future__ import annotations

import asyncio
import dataclasses
import uuid
from datetime import datetime, timezone
from typing import Mapping

from app.governance.context import GovernanceContext
from app.governance.decisions import GovernanceDecision, build_decision
from app.governance.enforcement.models import EnforcementAction
from app.governance.enforcement.handlers import EnforcementHandlerRegistry
from app.governance.envelopes import GovernanceEnvelope
from app.governance.enums import EnforcementStage
from app.governance.evaluators.engine import PolicyEvaluationEngine
from app.governance.exceptions import (
    EnforcementExecutionError,
    GovernanceConfigurationError,
)
from app.governance.identity.decision_ids import (
    derive_decision_id,
    generate_decision_id,
)
from app.governance.persistence import (
    BaseGovernanceRepository,
)
from app.governance.persistence.serializers import (
    decision_to_record,
    enforcement_action_to_record,
    trace_to_record,
)
from app.governance.policies.chain import PolicyChain
from app.governance.tracing import GovernanceTrace
from app.observability.audit import AuditEvent, emit_audit_event
from app.observability.context import get_request_id
from app.observability.governance_logging import (
    log_governance_evaluation,
    log_policy_evaluation,
)
from app.observability.governance_metrics import (
    record_enforcement_action,
    record_governance_evaluation,
)


class GovernanceRuntime:
    """Apex governance orchestrator. Produces one `GovernanceEnvelope`
    per call, never raises.
    """

    def __init__(
        self,
        *,
        engine: PolicyEvaluationEngine,
        handler_registry: EnforcementHandlerRegistry,
        chains: Mapping[EnforcementStage, PolicyChain],
        persistence: BaseGovernanceRepository | None = None,
    ) -> None:
        self._engine = engine
        self._handlers = handler_registry
        self._chains: dict[EnforcementStage, PolicyChain] = dict(chains)
        self._persistence = persistence

        # Fail-fast at composition: the registry MUST cover every
        # Decision value the substrate emits.
        self._handlers.assert_complete()

    # ─── Inspection helpers ──────────────────────────────────────────

    @property
    def supported_stages(self) -> tuple[EnforcementStage, ...]:
        return tuple(sorted(self._chains.keys(), key=lambda s: s.value))

    def chain_for(self, stage: EnforcementStage) -> PolicyChain | None:
        return self._chains.get(stage)

    # ─── Public API ───────────────────────────────────────────────────

    async def evaluate(
        self,
        context: GovernanceContext,
    ) -> GovernanceEnvelope:
        """Run the full pipeline for `context`. Never raises."""
        loop = asyncio.get_event_loop()
        started_at = datetime.now(timezone.utc)
        loop_start = loop.time()
        rid = context.request_id or get_request_id()
        if rid != context.request_id:
            # Propagate the request id from the platform-wide context
            # if the caller didn't set one. The context is frozen, so
            # we synthesise a copy.
            context = dataclasses.replace(context, request_id=rid)

        chain = self._chains.get(context.stage)
        if chain is None:
            return await self._fail_envelope(
                error=GovernanceConfigurationError(
                    f"no policy chain configured for stage "
                    f"{context.stage.value!r}"
                ),
                context=context,
                started_at=started_at,
                loop_start=loop_start,
                chain_id="",
            )

        # 1. Engine: run every policy in declared order.
        engine_result = await self._engine.evaluate(chain, context)
        for policy_trace in engine_result.policy_traces:
            log_policy_evaluation(policy_trace)

        decision_id = _decision_id_from_context_seed(context)

        # 2. Build the apex decision (pure-function aggregation).
        decision = build_decision(
            stage=context.stage,
            policy_chain_id=chain.chain_id,
            evaluation_results=engine_result.evaluation_results,
            metadata={
                **dict(context.metadata),
                "action": context.action,
                "resource": context.resource,
                "tenant_id": context.tenant_id,
                "subject_kind": context.subject.kind.value,
                # 2.5-C1: stamp request_id alongside the existing
                # tenant/subject/correlation triple so the decision
                # record can be queried by request_id at parity with
                # the trace record.
                "request_id": (
                    str(context.request_id)
                    if context.request_id is not None
                    else None
                ),
                "correlation_id": (
                    str(context.correlation_id)
                    if context.correlation_id is not None
                    else None
                ),
                # 2.5-E: governance build provenance flows from the
                # ``PolicyChain`` through here so the persisted
                # decision record carries the version pin.
                "governance_version": chain.governance_version,
            },
            decision_id=decision_id,
        )

        # 3. Enforcement.
        handler = self._handlers.get(decision.decision)
        enforcement_started = loop.time()
        try:
            action = await handler.apply(decision)
        except Exception as exc:
            # Handler failure: distinct from engine failure. The
            # decision is preserved (audit-grade) but the envelope is
            # marked failed so downstream consumers know enforcement
            # did NOT complete.
            err = EnforcementExecutionError(
                f"enforcement handler {handler.name!r} raised: "
                f"{type(exc).__name__}: {exc}",
                handler_name=handler.name,
                decision=decision,
                cause=exc,
            )
            ended_at = datetime.now(timezone.utc)
            latency_ms = round((loop.time() - loop_start) * 1000, 2)
            enforcement_latency_ms = round(
                (loop.time() - enforcement_started) * 1000, 2
            )
            trace = GovernanceTrace(
                decision_id=decision.decision_id,
                request_id=rid,
                stage=context.stage,
                action=context.action,
                resource=context.resource,
                actor=context.actor,
                tenant_id=context.tenant_id,
                started_at=started_at,
                ended_at=ended_at,
                latency_ms=latency_ms,
                status="failed",
                final_decision=decision.decision,
                policy_chain_id=chain.chain_id,
                policy_traces=engine_result.policy_traces,
                rule_count=len(decision.evaluated_rules),
                violation_count=len(decision.violations),
                restriction_count=len(decision.restrictions),
                subject_kind=context.subject.kind.value,
                correlation_id=context.correlation_id,
                enforcement_handler=handler.name,
                enforcement_status="failed",
                enforcement_latency_ms=enforcement_latency_ms,
                error=f"{type(exc).__name__}: {exc}",
                metadata=dict(context.metadata),
            )
            log_governance_evaluation(trace)
            record_governance_evaluation(
                stage=context.stage.value,
                action=context.action,
                tenant_id=context.tenant_id,
                policy_chain_id=chain.chain_id,
                final_decision=decision.decision.value,
                policy_count=len(engine_result.policy_traces),
                rule_count=len(decision.evaluated_rules),
                violation_count=len(decision.violations),
                restriction_count=len(decision.restrictions),
                latency_ms=latency_ms,
                status="failed",
            )
            await self._persist_failure(decision=decision, trace=trace)
            return GovernanceEnvelope(trace=trace, error=err)

        # 4. Successful enforcement.
        ended_at = datetime.now(timezone.utc)
        latency_ms = round((loop.time() - loop_start) * 1000, 2)
        enforcement_latency_ms = round(
            (loop.time() - enforcement_started) * 1000, 2
        )
        trace = GovernanceTrace(
            decision_id=decision.decision_id,
            request_id=rid,
            stage=context.stage,
            action=context.action,
            resource=context.resource,
            actor=context.actor,
            tenant_id=context.tenant_id,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            status="ok",
            final_decision=decision.decision,
            policy_chain_id=chain.chain_id,
            policy_traces=engine_result.policy_traces,
            rule_count=len(decision.evaluated_rules),
            violation_count=len(decision.violations),
            restriction_count=len(decision.restrictions),
            subject_kind=context.subject.kind.value,
            correlation_id=context.correlation_id,
            enforcement_handler=handler.name,
            enforcement_status="ok",
            enforcement_latency_ms=enforcement_latency_ms,
            metadata=dict(context.metadata),
        )
        log_governance_evaluation(trace)
        record_governance_evaluation(
            stage=context.stage.value,
            action=context.action,
            tenant_id=context.tenant_id,
            policy_chain_id=chain.chain_id,
            final_decision=decision.decision.value,
            policy_count=len(engine_result.policy_traces),
            rule_count=len(decision.evaluated_rules),
            violation_count=len(decision.violations),
            restriction_count=len(decision.restrictions),
            latency_ms=latency_ms,
            status="ok",
        )
        record_enforcement_action(
            handler_name=handler.name,
            decision=decision.decision.value,
            outcome=action.outcome.value,
            latency_ms=enforcement_latency_ms,
        )
        emit_audit_event(
            AuditEvent(
                actor=context.actor,
                action=f"governance.{context.stage.value}",
                resource=context.resource,
                metadata={
                    "decision_id": str(decision.decision_id),
                    "final_decision": decision.decision.value,
                    "policy_chain_id": chain.chain_id,
                    "violation_count": len(decision.violations),
                    "restriction_count": len(decision.restrictions),
                    "tenant_id": context.tenant_id,
                    "rule_count": len(decision.evaluated_rules),
                    "enforcement_handler": handler.name,
                    "enforcement_outcome": action.outcome.value,
                },
                request_id=rid,
            )
        )

        await self._persist_success(
            decision=decision,
            trace=trace,
            action=action,
        )
        return GovernanceEnvelope(trace=trace, decision=decision)

    # ─── Internals ────────────────────────────────────────────────────

    async def _fail_envelope(
        self,
        *,
        error: BaseException,
        context: GovernanceContext,
        started_at: datetime,
        loop_start: float,
        chain_id: str,
    ) -> GovernanceEnvelope:
        loop = asyncio.get_event_loop()
        ended_at = datetime.now(timezone.utc)
        latency_ms = round((loop.time() - loop_start) * 1000, 2)
        decision_id = (
            _decision_id_from_context_seed(context)
            or generate_decision_id()
        )
        decision = build_decision(
            stage=context.stage,
            policy_chain_id=chain_id,
            evaluation_results=(),
            metadata={
                **dict(context.metadata),
                "action": context.action,
                "resource": context.resource,
                "tenant_id": context.tenant_id,
                "subject_kind": context.subject.kind.value,
                "request_id": (
                    str(context.request_id)
                    if context.request_id is not None
                    else None
                ),
                "correlation_id": (
                    str(context.correlation_id)
                    if context.correlation_id is not None
                    else None
                ),
                "governance_version": "unversioned",
                "failure": type(error).__name__,
            },
            decided_at=ended_at,
            decision_id=decision_id,
        )

        trace = GovernanceTrace(
            decision_id=decision.decision_id,
            request_id=context.request_id,
            stage=context.stage,
            action=context.action,
            resource=context.resource,
            actor=context.actor,
            tenant_id=context.tenant_id,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            status="failed",
            final_decision=decision.decision,
            policy_chain_id=chain_id,
            policy_traces=(),
            rule_count=len(decision.evaluated_rules),
            violation_count=len(decision.violations),
            restriction_count=len(decision.restrictions),
            subject_kind=context.subject.kind.value,
            correlation_id=context.correlation_id,
            error=f"{type(error).__name__}: {error}",
            metadata=dict(context.metadata),
        )
        log_governance_evaluation(trace)
        record_governance_evaluation(
            stage=context.stage.value,
            action=context.action,
            tenant_id=context.tenant_id,
            policy_chain_id=chain_id,
            final_decision=decision.decision.value,
            policy_count=0,
            rule_count=len(decision.evaluated_rules),
            violation_count=len(decision.violations),
            restriction_count=len(decision.restrictions),
            latency_ms=latency_ms,
            status="failed",
        )
        await self._persist_failure(decision=decision, trace=trace)
        return GovernanceEnvelope(trace=trace, error=error)

    async def _persist_success(
        self,
        *,
        decision: GovernanceDecision,
        trace: GovernanceTrace,
        action: EnforcementAction,
    ) -> None:
        if self._persistence is None:
            return
        await self._persistence.record_decision(
            decision_to_record(decision)
        )
        await self._persistence.record_trace(trace_to_record(trace))
        await self._persistence.record_enforcement_action(
            enforcement_action_to_record(action)
        )

    async def _persist_failure(
        self,
        *,
        decision: GovernanceDecision,
        trace: GovernanceTrace,
    ) -> None:
        if self._persistence is None:
            return
        await self._persistence.record_decision(
            decision_to_record(decision)
        )
        await self._persistence.record_trace(trace_to_record(trace))


def _decision_id_from_context_seed(
    context: GovernanceContext,
) -> uuid.UUID | None:
    seed = context.metadata.get("governance.decision_seed")
    if not isinstance(seed, str) or not seed:
        return None
    return derive_decision_id(seed=seed)


__all__ = ["GovernanceRuntime"]

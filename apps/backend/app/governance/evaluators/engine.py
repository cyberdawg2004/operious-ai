"""Policy evaluation engine implementation.

See `app/governance/evaluators/__init__.py` for the architectural
contract this module honours.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from app.governance.context import GovernanceContext
from app.governance.decisions import PolicyEvaluationResult
from app.governance.enums import Decision, ViolationSeverity
from app.governance.policies.chain import PolicyChain
from app.governance.tracing import PolicyEvaluationTrace


@dataclass(frozen=True, slots=True)
class EngineEvaluationResult:
    """What the engine returns to the runtime.

    Two parallel tuples, both ordered to match the chain's policy
    declaration order:

    * `evaluation_results` — flat tuple of every rule-level result
      every policy produced. Drives the decision builder.
    * `policy_traces` — one trace per policy invocation. Drives the
      observability sinks.

    The split exists because the decision builder cares about results
    (semantic verdicts) while the trace stream cares about invocations
    (operational metadata). One producer, two consumers, no mixing.
    """

    evaluation_results: tuple[PolicyEvaluationResult, ...]
    policy_traces: tuple[PolicyEvaluationTrace, ...]


class PolicyEvaluationEngine:
    """Deterministic coordinator: chain × context → results + traces."""

    async def evaluate(
        self,
        chain: PolicyChain,
        context: GovernanceContext,
    ) -> EngineEvaluationResult:
        """Run every policy in `chain` against `context` in declared order."""
        flat_results: list[PolicyEvaluationResult] = []
        policy_traces: list[PolicyEvaluationTrace] = []

        loop = asyncio.get_event_loop()
        for policy in chain.policies:
            started_at = datetime.now(timezone.utc)
            loop_start = loop.time()

            # Sprint I Hardening: subject-kind applicability gate.
            # Policies declare which subject kinds they handle via
            # `applicable_subject_kinds`. Empty frozenset means "any";
            # otherwise the engine skips the policy and emits a
            # `"skipped"` trace. No result is produced — the policy is
            # silent for this evaluation.
            if not policy.applies_to(context.subject.kind):
                ended_at = datetime.now(timezone.utc)
                latency_ms = round((loop.time() - loop_start) * 1000, 2)
                policy_traces.append(
                    PolicyEvaluationTrace(
                        policy_name=policy.name,
                        status="skipped",
                        started_at=started_at,
                        ended_at=ended_at,
                        latency_ms=latency_ms,
                        rule_count=0,
                        decision_counts=_count(()),
                        metadata={
                            "skip_reason": "subject_kind_not_applicable",
                            "subject_kind": context.subject.kind.value,
                        },
                    )
                )
                continue

            try:
                results = tuple(await policy.evaluate(context))
            except Exception as exc:
                # Fail-safe: a policy that raises produces a synthetic
                # DENY so the substrate refuses to proceed on a broken
                # rule rather than silently passing.
                ended_at = datetime.now(timezone.utc)
                latency_ms = round((loop.time() - loop_start) * 1000, 2)
                synthetic = PolicyEvaluationResult(
                    policy_name=policy.name,
                    rule_id="evaluation_error",
                    decision=Decision.DENY,
                    severity=ViolationSeverity.CRITICAL,
                    reason=f"policy raised: {type(exc).__name__}: {exc}",
                    metadata={"exception_type": type(exc).__name__},
                )
                flat_results.append(synthetic)
                policy_traces.append(
                    PolicyEvaluationTrace(
                        policy_name=policy.name,
                        status="failed",
                        started_at=started_at,
                        ended_at=ended_at,
                        latency_ms=latency_ms,
                        rule_count=0,
                        decision_counts=_count(()),
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
                continue

            ended_at = datetime.now(timezone.utc)
            latency_ms = round((loop.time() - loop_start) * 1000, 2)
            flat_results.extend(results)
            policy_traces.append(
                PolicyEvaluationTrace(
                    policy_name=policy.name,
                    status="ok",
                    started_at=started_at,
                    ended_at=ended_at,
                    latency_ms=latency_ms,
                    rule_count=len(results),
                    decision_counts=_count(results),
                )
            )

        return EngineEvaluationResult(
            evaluation_results=tuple(flat_results),
            policy_traces=tuple(policy_traces),
        )


def _count(
    results: tuple[PolicyEvaluationResult, ...] | tuple[()],
) -> dict[Decision, int]:
    counter: Counter[Decision] = Counter(r.decision for r in results)
    return dict(counter)


__all__ = ["EngineEvaluationResult", "PolicyEvaluationEngine"]

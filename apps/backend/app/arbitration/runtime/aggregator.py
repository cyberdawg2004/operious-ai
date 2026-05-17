"""`build_arbitration_decision` — single authority on apex aggregation.

The aggregator is the **only** function that decides the apex
`ArbitrationOutcome`. No evaluator, no caller, no other runtime
re-encodes this logic.

Aggregation rules (most-authoritative-wins; never voting):

1. **Deadlock dominates**. If ANY deadlock witness was emitted,
   outcome is `ARBITRATION_DEADLOCK` and `prevailing_authority` is
   ``None``. The substrate refuses to resolve a case in a deadlock
   pattern.

2. **No signals → INCONCLUSIVE**. If the case carries no signals,
   the substrate has nothing to interpret.

3. **Highest-authority group**:
   * compute the minimum precedence (= highest authority) across
     all signals,
   * collect every signal at that precedence (the "top group").

4. **Within the top group**:
   * if all signals carry the same verdict and that verdict is
     `ESCALATE` → `ARBITRATION_ESCALATED`,
   * if all carry the same verdict and that verdict is `UNKNOWN`
     → `ARBITRATION_INCONCLUSIVE` (no definite opinion),
   * if all carry the same verdict otherwise →
     `ARBITRATION_RESOLVED`,
   * if verdicts differ → `ARBITRATION_CONFLICT`,
     `prevailing_authority = None`.

5. Lower-authority disagreements are recorded as audit conflicts
   but **do not override** the top group's verdict.

6. The prevailing source within the top group is the FIRST signal
   in case order. Deterministic, replay-safe, and audit-stable.

The aggregator never executes, dispatches, retries, or mutates
state. It is a pure function.
"""

from __future__ import annotations

from typing import Iterable

from app.arbitration.enums import (
    ArbitrationOutcome,
    ArbitrationVerdictKind,
)
from app.arbitration.models.authority import ResolutionAuthority
from app.arbitration.models.conflict import ArbitrationConflict
from app.arbitration.models.deadlock import DeadlockWitness
from app.arbitration.models.decision import ArbitrationDecision
from app.arbitration.models.signal import ArbitrationSignal
from app.arbitration.taxonomy import (
    arbitration_authority_precedence,
)


def build_arbitration_decision(
    *,
    signals: Iterable[ArbitrationSignal],
    conflicts: Iterable[ArbitrationConflict],
    deadlock_witnesses: Iterable[DeadlockWitness],
) -> ArbitrationDecision:
    """Compute the apex `ArbitrationDecision` for one case."""
    signal_tuple = tuple(signals)
    conflict_tuple = tuple(conflicts)
    witness_tuple = tuple(deadlock_witnesses)

    # ── (1) Deadlock dominates ───────────────────────────────────
    if witness_tuple:
        kinds = ", ".join(sorted({w.kind.value for w in witness_tuple}))
        return ArbitrationDecision(
            outcome=ArbitrationOutcome.ARBITRATION_DEADLOCK,
            prevailing_authority=None,
            reason=f"deadlock pattern(s) detected: {kinds}",
        )

    # ── (2) No signals → INCONCLUSIVE ────────────────────────────
    if not signal_tuple:
        return ArbitrationDecision(
            outcome=ArbitrationOutcome.ARBITRATION_INCONCLUSIVE,
            prevailing_authority=None,
            reason="no signals submitted",
        )

    # ── (3) Top-authority group ──────────────────────────────────
    min_precedence = min(
        arbitration_authority_precedence(s.authority)
        for s in signal_tuple
    )
    top_signals = tuple(
        s
        for s in signal_tuple
        if arbitration_authority_precedence(s.authority)
        == min_precedence
    )
    top_verdicts = {s.verdict for s in top_signals}

    # ── (4) Verdict aggregation within top group ─────────────────
    if len(top_verdicts) == 1:
        prevailing_signal = top_signals[0]
        only_verdict = next(iter(top_verdicts))
        prevailing = ResolutionAuthority(
            level=prevailing_signal.authority,
            source_substrate=prevailing_signal.source_substrate,
            source_id=prevailing_signal.source_id,
            verdict=only_verdict.value,
            reason=prevailing_signal.reason,
        )
        lower_conflict_note = (
            f" lower-authority conflicts recorded: "
            f"{len(conflict_tuple)}"
            if conflict_tuple
            else ""
        )
        if only_verdict is ArbitrationVerdictKind.ESCALATE:
            return ArbitrationDecision(
                outcome=ArbitrationOutcome.ARBITRATION_ESCALATED,
                prevailing_authority=prevailing,
                reason=(
                    f"prevailing authority "
                    f"{prevailing_signal.authority.value}"
                    f":{prevailing_signal.source_substrate}"
                    f":{prevailing_signal.source_id} ESCALATE"
                    f"{lower_conflict_note}"
                ),
            )
        if only_verdict is ArbitrationVerdictKind.UNKNOWN:
            return ArbitrationDecision(
                outcome=ArbitrationOutcome.ARBITRATION_INCONCLUSIVE,
                prevailing_authority=None,
                reason=(
                    f"top authority "
                    f"{prevailing_signal.authority.value} reported "
                    f"UNKNOWN; no definite opinion to interpret."
                ),
            )
        return ArbitrationDecision(
            outcome=ArbitrationOutcome.ARBITRATION_RESOLVED,
            prevailing_authority=prevailing,
            reason=(
                f"prevailing authority "
                f"{prevailing_signal.authority.value}"
                f":{prevailing_signal.source_substrate}"
                f":{prevailing_signal.source_id} "
                f"{only_verdict.value}"
                f"{lower_conflict_note}"
            ),
        )

    # ── Disagreement at top authority → CONFLICT ─────────────────
    verdict_summary = ", ".join(
        sorted({v.value for v in top_verdicts})
    )
    return ArbitrationDecision(
        outcome=ArbitrationOutcome.ARBITRATION_CONFLICT,
        prevailing_authority=None,
        reason=(
            f"top authority "
            f"{top_signals[0].authority.value} signals disagree: "
            f"{verdict_summary}"
        ),
    )


__all__ = ["build_arbitration_decision"]

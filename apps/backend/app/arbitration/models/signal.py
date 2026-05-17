"""`ArbitrationSignal` — one input observation in a case.

The signal is the **substrate-agnostic** input shape. The
arbitration runtime never imports sibling-substrate runtimes. Any
caller (an inspection adapter outside this package) translates a
substrate-specific finding / verdict / outcome into an
`ArbitrationSignal` and submits it as part of an
`ArbitrationCase`.

Signal authority is set by the caller — the arbitration substrate
trusts the declared `authority` (it is structurally derived from
WHICH substrate emitted the observation, not from the verdict
itself). Arbitration evaluators NEVER promote a signal to higher
authority.

A signal does NOT carry a confidence score or weight. Voting and
weighted aggregation are explicitly forbidden by Sprint L4. The
only aggregation rule is most-authoritative-wins.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.arbitration.enums import (
    ArbitrationAuthorityLevel,
    ArbitrationVerdictKind,
)
from app.arbitration.identity import ArbitrationSignalId


@dataclass(frozen=True, slots=True)
class ArbitrationSignal:
    """One substrate-agnostic input signal.

    Attributes:
        signal_id:        Stable identifier (replay-safe via
                           `derive_signal_id` when used in tests).
        authority:        Authority level the signal originates at.
                           Used by aggregation. Never mutated.
        verdict:          What the signal asserts.
        source_substrate: Short string naming the originating
                           substrate (e.g. ``governance``,
                           ``coordination.policy``,
                           ``supervisor``). Surfaces verbatim in
                           audit; the substrate does not interpret
                           the string semantically.
        source_id:        Stable identifier within the source
                           substrate (e.g. a governance decision id,
                           a supervisor id). The arbitration
                           substrate does not validate it.
        reason:           Short human-readable rationale.
        emitted_at:       Wall-clock timestamp from the source.
        metadata:         Free-form, propagated through persistence.
    """

    signal_id: ArbitrationSignalId
    authority: ArbitrationAuthorityLevel
    verdict: ArbitrationVerdictKind
    source_substrate: str
    source_id: str
    reason: str = ""
    emitted_at: datetime | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


__all__ = ["ArbitrationSignal"]

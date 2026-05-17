"""Byte-identical replay-equivalence validator.

Compares two payloads via canonical JSON fingerprinting.
Returns a `ReplayEquivalenceFinding`. The validator NEVER
re-executes, NEVER mutates, and NEVER touches runtime state.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.hardening.enums import ReplayStatus
from app.hardening.identity import derive_finding_id
from app.hardening.models.replay import (
    ReplayEquivalenceFinding,
)
from app.hardening.serializers.canonical import (
    content_fingerprint,
)


def validate_replay_equivalence(
    *,
    canonical_payload: Any,
    candidate_payload: Any,
    seed: str,
    scope: str | None = None,
    detected_at: datetime | None = None,
) -> ReplayEquivalenceFinding:
    if not seed:
        raise ValueError(
            "validate_replay_equivalence requires a non-empty seed"
        )
    if detected_at is None:
        detected_at = datetime.now().astimezone()
    if detected_at.tzinfo is None:
        raise ValueError(
            "validate_replay_equivalence.detected_at must be tz-aware"
        )
    canonical_fp = content_fingerprint(canonical_payload)
    candidate_fp = content_fingerprint(candidate_payload)

    if canonical_fp == candidate_fp:
        status = ReplayStatus.BYTE_IDENTICAL
        diff_summary = None
    else:
        status = ReplayStatus.DRIFTED
        diff_summary = (
            f"fingerprint mismatch: canonical={canonical_fp[:16]} "
            f"candidate={candidate_fp[:16]}"
        )

    return ReplayEquivalenceFinding(
        finding_id=derive_finding_id(
            audit_seed=seed,
            kind=status.value,
            ordinal=0,
        ),
        status=status,
        canonical_fingerprint=canonical_fp,
        candidate_fingerprint=candidate_fp,
        diff_summary=diff_summary,
        detected_at=detected_at,
        scope=scope,
    )


class ReplayIntegrityValidator:
    """Stateless object form of `validate_replay_equivalence`."""

    __slots__ = ()

    def validate(
        self,
        *,
        canonical_payload: Any,
        candidate_payload: Any,
        seed: str,
        scope: str | None = None,
        detected_at: datetime | None = None,
    ) -> ReplayEquivalenceFinding:
        return validate_replay_equivalence(
            canonical_payload=canonical_payload,
            candidate_payload=candidate_payload,
            seed=seed,
            scope=scope,
            detected_at=detected_at,
        )


__all__ = [
    "ReplayIntegrityValidator",
    "validate_replay_equivalence",
]

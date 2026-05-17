"""Reconstruction verifier — original-vs-reconstructed equivalence."""

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


def validate_reconstruction(
    *,
    original_payload: Any,
    reconstructed_payload: Any,
    seed: str,
    scope: str | None = None,
    detected_at: datetime | None = None,
) -> ReplayEquivalenceFinding:
    if not seed:
        raise ValueError(
            "validate_reconstruction requires a non-empty seed"
        )
    if detected_at is None:
        detected_at = datetime.now().astimezone()
    if detected_at.tzinfo is None:
        raise ValueError(
            "validate_reconstruction.detected_at must be tz-aware"
        )
    original_fp = content_fingerprint(original_payload)
    reconstructed_fp = content_fingerprint(
        reconstructed_payload
    )

    if original_fp == reconstructed_fp:
        status = ReplayStatus.BYTE_IDENTICAL
        diff_summary = None
    else:
        status = ReplayStatus.DRIFTED
        diff_summary = (
            f"reconstruction drift: original={original_fp[:16]} "
            f"reconstructed={reconstructed_fp[:16]}"
        )

    return ReplayEquivalenceFinding(
        finding_id=derive_finding_id(
            audit_seed=seed,
            kind=f"reconstruction:{status.value}",
            ordinal=0,
        ),
        status=status,
        canonical_fingerprint=original_fp,
        candidate_fingerprint=reconstructed_fp,
        diff_summary=diff_summary,
        detected_at=detected_at,
        scope=scope,
    )


class ReconstructionVerifier:
    __slots__ = ()

    def verify(
        self,
        *,
        original_payload: Any,
        reconstructed_payload: Any,
        seed: str,
        scope: str | None = None,
        detected_at: datetime | None = None,
    ) -> ReplayEquivalenceFinding:
        return validate_reconstruction(
            original_payload=original_payload,
            reconstructed_payload=reconstructed_payload,
            seed=seed,
            scope=scope,
            detected_at=detected_at,
        )


__all__ = [
    "ReconstructionVerifier",
    "validate_reconstruction",
]

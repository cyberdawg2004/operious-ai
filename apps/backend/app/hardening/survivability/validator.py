"""Survivability validator.

The substrate observes whether persisted records survived a
distributed failure. It does not heal anything; it only
classifies.
"""

from __future__ import annotations

from datetime import datetime

from app.hardening.enums import SurvivabilityStatus
from app.hardening.identity import derive_finding_id
from app.hardening.models.survivability import (
    SurvivabilityFinding,
)


def validate_survivability(
    *,
    expected_count: int,
    survived_count: int,
    seed: str,
    scope: str | None = None,
    detected_at: datetime | None = None,
) -> SurvivabilityFinding:
    if not seed:
        raise ValueError(
            "validate_survivability requires a non-empty seed"
        )
    if expected_count < 0 or survived_count < 0:
        raise ValueError(
            "expected_count/survived_count must be >= 0"
        )
    if survived_count > expected_count:
        raise ValueError(
            "survived_count cannot exceed expected_count"
        )
    if detected_at is None:
        detected_at = datetime.now().astimezone()
    if detected_at.tzinfo is None:
        raise ValueError(
            "validate_survivability.detected_at must be tz-aware"
        )

    if expected_count == 0:
        status = SurvivabilityStatus.UNVERIFIABLE
    elif survived_count == expected_count:
        status = SurvivabilityStatus.SURVIVED
    elif survived_count == 0:
        status = SurvivabilityStatus.LOST
    else:
        status = SurvivabilityStatus.PARTIALLY_SURVIVED

    return SurvivabilityFinding(
        finding_id=derive_finding_id(
            audit_seed=seed,
            kind=f"survivability:{status.value}",
            ordinal=0,
        ),
        status=status,
        survived_count=survived_count,
        expected_count=expected_count,
        scope=scope,
        detected_at=detected_at,
    )


class SurvivabilityValidator:
    __slots__ = ()

    def validate(
        self,
        *,
        expected_count: int,
        survived_count: int,
        seed: str,
        scope: str | None = None,
        detected_at: datetime | None = None,
    ) -> SurvivabilityFinding:
        return validate_survivability(
            expected_count=expected_count,
            survived_count=survived_count,
            seed=seed,
            scope=scope,
            detected_at=detected_at,
        )


__all__ = [
    "SurvivabilityValidator",
    "validate_survivability",
]

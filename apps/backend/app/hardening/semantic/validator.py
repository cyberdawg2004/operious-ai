"""`OwnershipInvariantValidator` — pure semantic-ownership validation.

The validator never mutates anything. It accepts a snapshot of
caller-observed substrate ownership and emits one
`BoundaryViolationFinding` per offender that is in the
boundary's ``forbidden_owners``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Mapping

from app.hardening.enums import (
    HardeningSeverity,
    SubstrateName,
)
from app.hardening.identity import (
    derive_violation_id,
)
from app.hardening.models.ownership import (
    AuthorityOwnershipMap,
    CANONICAL_AUTHORITY_OWNERSHIP_MAP,
)
from app.hardening.models.violation import (
    BoundaryViolationFinding,
)


def validate_authority_ownership(
    *,
    observed_owners: Mapping[
        str, tuple[SubstrateName, ...]
    ],
    map_: AuthorityOwnershipMap | None = None,
    detected_at: datetime | None = None,
) -> tuple[BoundaryViolationFinding, ...]:
    """Pure deterministic validator.

    For each `(concern, observed_substrates)` pair, emit a
    violation finding for every observed substrate that is in
    the boundary's ``forbidden_owners``.

    Findings are returned sorted by ``(concern, offender)``.
    """
    if map_ is None:
        map_ = CANONICAL_AUTHORITY_OWNERSHIP_MAP
    if detected_at is None:
        detected_at = datetime.now().astimezone()
    if detected_at.tzinfo is None:
        raise ValueError(
            "validate_authority_ownership.detected_at must be "
            "tz-aware"
        )
    findings: list[BoundaryViolationFinding] = []
    for concern in sorted(observed_owners.keys()):
        boundary = map_.boundary_for(concern)
        if boundary is None:
            continue
        observed = observed_owners[concern]
        for offender in sorted(set(observed), key=lambda s: s.value):
            if offender == boundary.owner:
                continue
            if offender not in boundary.forbidden_owners:
                continue
            findings.append(
                BoundaryViolationFinding(
                    violation_id=derive_violation_id(
                        boundary_concern=concern,
                        offender=offender.value,
                        detail="forbidden_observer",
                    ),
                    boundary_concern=concern,
                    rightful_owner=boundary.owner,
                    offender=offender,
                    offender_location=None,
                    severity=HardeningSeverity.HIGH,
                    summary=(
                        f"{offender.value} observed touching "
                        f"{concern!r}; rightful owner is "
                        f"{boundary.owner.value}"
                    ),
                    detected_at=detected_at,
                    evidence=tuple(
                        sorted(
                            {s.value for s in observed if s != boundary.owner}
                        )
                    ),
                )
            )
    return tuple(findings)


class OwnershipInvariantValidator:
    """Stateless object form of `validate_authority_ownership`."""

    __slots__ = ("_map",)

    def __init__(
        self, map_: AuthorityOwnershipMap | None = None
    ) -> None:
        self._map = map_ or CANONICAL_AUTHORITY_OWNERSHIP_MAP

    @property
    def map(self) -> AuthorityOwnershipMap:
        return self._map

    def validate(
        self,
        *,
        observed_owners: Mapping[
            str, tuple[SubstrateName, ...]
        ],
        detected_at: datetime | None = None,
    ) -> tuple[BoundaryViolationFinding, ...]:
        return validate_authority_ownership(
            observed_owners=observed_owners,
            map_=self._map,
            detected_at=detected_at,
        )


__all__ = [
    "OwnershipInvariantValidator",
    "validate_authority_ownership",
]

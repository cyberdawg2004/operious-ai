"""Deterministic-ordering validator."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from app.hardening.enums import (
    HardeningFindingKind,
    HardeningSeverity,
    IntegrityStatus,
)
from app.hardening.identity import derive_finding_id
from app.hardening.models.finding import HardeningFinding


def validate_ordering(
    *,
    items: tuple[Any, ...],
    key_fn: Callable[[Any], Any],
    seed: str,
    detected_at: datetime | None = None,
    scope: str | None = None,
) -> tuple[
    tuple[HardeningFinding, ...], IntegrityStatus
]:
    """Run ``key_fn`` over ``items`` and assert the result is sorted."""
    if not seed:
        raise ValueError(
            "validate_ordering requires a non-empty seed"
        )
    if detected_at is None:
        detected_at = datetime.now().astimezone()
    if detected_at.tzinfo is None:
        raise ValueError(
            "validate_ordering.detected_at must be tz-aware"
        )

    findings: list[HardeningFinding] = []
    keys = [key_fn(item) for item in items]
    sorted_keys = sorted(keys)
    if keys != sorted_keys:
        offenders: list[str] = []
        for idx in range(1, len(keys)):
            if keys[idx - 1] > keys[idx]:
                offenders.append(
                    f"index {idx - 1}={keys[idx - 1]!r} > "
                    f"index {idx}={keys[idx]!r}"
                )
        findings.append(
            HardeningFinding(
                finding_id=derive_finding_id(
                    audit_seed=seed,
                    kind=HardeningFindingKind.ORDERING_NONDETERMINISM.value,
                    ordinal=0,
                ),
                ordinal=0,
                kind=HardeningFindingKind.ORDERING_NONDETERMINISM,
                severity=HardeningSeverity.HIGH,
                summary="iteration order is not deterministic",
                detected_at=detected_at,
                scope=scope,
                evidence=tuple(offenders),
            )
        )
    status = (
        IntegrityStatus.PASSED
        if not findings
        else IntegrityStatus.FAILED
    )
    return tuple(findings), status


class OrderingValidator:
    __slots__ = ()

    def validate(
        self,
        *,
        items: tuple[Any, ...],
        key_fn: Callable[[Any], Any],
        seed: str,
        detected_at: datetime | None = None,
        scope: str | None = None,
    ) -> tuple[
        tuple[HardeningFinding, ...], IntegrityStatus
    ]:
        return validate_ordering(
            items=items,
            key_fn=key_fn,
            seed=seed,
            detected_at=detected_at,
            scope=scope,
        )


__all__ = ["OrderingValidator", "validate_ordering"]
